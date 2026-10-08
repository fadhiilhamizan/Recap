"""Adapter engine STT untuk benchmark.

- ``transcribe_cpp``: runtime ggml transcribe.cpp (Whisper, Qwen3-ASR, dll.) via binding Python resmi.
- ``whisper_cpp_cli``: binary resmi whisper.cpp (``whisper-cli.exe``) sebagai pembanding/paritas.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import psutil

from .audio import save_wav


@dataclass
class EngineResult:
    text: str
    proc_s: float  # waktu inferensi murni (tanpa load model)
    language: str | None = None
    note: str | None = None


@dataclass
class EngineSpec:
    """Konfigurasi satu engine. Disimpan apa adanya di hasil benchmark."""

    name: str
    kind: str  # "transcribe_cpp" | "whisper_cpp_cli"
    model: str  # path relatif terhadap .data/models
    backend: str = "cpu"  # cpu | vulkan | auto
    threads: int = 0  # 0 = default runtime
    language_mode: str = "fixed"  # fixed | auto
    options: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "EngineSpec":
        return cls(**d)


class Engine:
    spec: EngineSpec
    load_s: float = 0.0
    peak_child_rss: int = 0

    def transcribe(self, pcm: np.ndarray, language: str | None, prompt: str | None = None) -> EngineResult:
        raise NotImplementedError

    def close(self) -> None:
        pass


class TranscribeCppEngine(Engine):
    def __init__(self, spec: EngineSpec, models_dir: Path):
        import transcribe_cpp as tc

        self.tc = tc
        self.spec = spec
        path = models_dir / spec.model
        t0 = time.perf_counter()
        self.model = tc.Model(str(path), backend=spec.backend)
        self.session = self.model.session(n_threads=spec.threads)
        self.load_s = time.perf_counter() - t0
        self.arch = getattr(self.model, "arch", None)
        self._language_supported: bool | None = None

    def _run(self, pcm: np.ndarray, **kw):
        family = None
        opts = dict(self.spec.options.get("whisper", {}))
        if opts and str(self.arch).lower().startswith("whisper"):
            family = self.tc.WhisperRunOptions(**opts)
        return self.session.run(pcm, timestamps="none", family=family, **kw)

    def transcribe(self, pcm, language, prompt=None):
        kw: dict = {}
        if self.spec.language_mode == "fixed" and language and self._language_supported is not False:
            kw["language"] = language
        if prompt:
            kw["prompt"] = prompt
        note = None
        t0 = time.perf_counter()
        try:
            res = self._run(pcm, **kw)
            if "language" in kw:
                self._language_supported = True
        except (self.tc.UnsupportedRequest, self.tc.InvalidArgument) as exc:
            # Model tidak menerima pengunci bahasa (misalnya hanya auto-detect): ulangi tanpa itu.
            if "language" not in kw:
                raise
            self._language_supported = False
            kw.pop("language")
            note = f"language ignored: {exc}"
            t0 = time.perf_counter()
            res = self._run(pcm, **kw)
        proc = time.perf_counter() - t0
        return EngineResult(text=res.text or "", proc_s=proc, language=getattr(res, "language", None), note=note)

    def close(self):
        self.session.close()
        self.model.close()


_TIMING_RE = re.compile(r"whisper_print_timings:\s+(load|total) time\s*=\s*([\d.]+) ms")


class WhisperCppCliEngine(Engine):
    """Menjalankan whisper-cli.exe per segmen. Waktu proses = total - load (dari log whisper.cpp)."""

    def __init__(self, spec: EngineSpec, models_dir: Path, bin_dir: Path):
        self.spec = spec
        self.exe = bin_dir / spec.options.get("exe", "whisper-cli.exe")
        self.model_path = models_dir / spec.model
        if not self.exe.exists():
            raise FileNotFoundError(self.exe)
        self.tmp = Path(tempfile.mkdtemp(prefix="recap-wcpp-"))

    def transcribe(self, pcm, language, prompt=None):
        wav = self.tmp / "seg.wav"
        save_wav(wav, pcm)
        cmd = [str(self.exe), "-m", str(self.model_path), "-f", str(wav), "-nt", "-np", "-otxt", "-of", str(self.tmp / "out")]
        if self.spec.threads:
            cmd += ["-t", str(self.spec.threads)]
        cmd += ["-l", language if (self.spec.language_mode == "fixed" and language) else "auto"]
        if prompt:
            cmd += ["--prompt", prompt]
        cmd += [str(x) for x in self.spec.options.get("extra_args", [])]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        peak = _watch_peak_rss(proc.pid)
        out, err = proc.communicate()
        self.peak_child_rss = max(self.peak_child_rss, peak.stop())
        if proc.returncode != 0:
            raise RuntimeError(f"whisper-cli gagal ({proc.returncode}): {err[-2000:]}")
        timings = dict((k, float(v)) for k, v in _TIMING_RE.findall(err))
        proc_s = (timings.get("total", 0.0) - timings.get("load", 0.0)) / 1000.0
        text = (self.tmp / "out.txt").read_text(encoding="utf-8", errors="replace").strip()
        return EngineResult(text=" ".join(text.split()), proc_s=proc_s)


class _PeakWatcher:
    def __init__(self, pid: int):
        self.pid = pid
        self.peak = 0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        try:
            p = psutil.Process(self.pid)
            while not self._stop.is_set():
                self.peak = max(self.peak, p.memory_info().rss)
                time.sleep(0.05)
        except psutil.Error:
            pass

    def stop(self) -> int:
        self._stop.set()
        self._t.join(timeout=1)
        return self.peak


def _watch_peak_rss(pid: int) -> _PeakWatcher:
    return _PeakWatcher(pid)


def create_engine(spec: EngineSpec, data_dir: Path) -> Engine:
    models_dir = data_dir / "models"
    if spec.kind == "transcribe_cpp":
        return TranscribeCppEngine(spec, models_dir)
    if spec.kind == "whisper_cpp_cli":
        return WhisperCppCliEngine(spec, models_dir, data_dir / "bin" / "whisper.cpp")
    raise ValueError(f"engine tidak dikenal: {spec.kind}")
