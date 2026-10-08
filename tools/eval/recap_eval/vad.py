"""Silero VAD (ONNX) dan segmenter sesuai desain dokumen 05 bagian 2.2.

Implementasi ini sengaja meniru logika yang nanti ditulis ulang di Rust (`recap-asr`),
sehingga parameter yang dikalibrasi di spike bisa dipindahkan apa adanya.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort

SR = 16_000
FRAME = 512  # 32 ms pada 16 kHz
CONTEXT = 64


@dataclass(frozen=True)
class VadParams:
    threshold: float = 0.5
    neg_threshold: float = 0.35
    min_speech_ms: int = 250
    redemption_ms: int = 1500  # sunyi untuk menutup segmen (final pass); live memakai sekitar 600
    pad_ms: int = 300
    max_segment_s: float = 28.0
    min_segment_s: float = 1.0  # segmen lebih pendek dipad sampai panjang ini saat dikirim ke STT

    @classmethod
    def live(cls) -> "VadParams":
        return cls(redemption_ms=600, pad_ms=200, max_segment_s=20.0)


@dataclass(frozen=True)
class Segment:
    start: int  # sample
    end: int  # sample (eksklusif)

    @property
    def start_s(self) -> float:
        return self.start / SR

    @property
    def end_s(self) -> float:
        return self.end / SR


class SileroVad:
    def __init__(self, model_path: str | Path, threads: int = 1):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])

    def probabilities(self, pcm: np.ndarray) -> np.ndarray:
        """Probabilitas ucapan per frame 32 ms."""
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, CONTEXT), dtype=np.float32)
        sr = np.array(SR, dtype=np.int64)
        n_frames = len(pcm) // FRAME
        probs = np.empty(n_frames, dtype=np.float32)
        for i in range(n_frames):
            frame = pcm[i * FRAME:(i + 1) * FRAME].reshape(1, FRAME)
            x = np.concatenate([context, frame], axis=1)
            out, state = self.session.run(None, {"input": x, "state": state, "sr": sr})
            probs[i] = float(out.reshape(-1)[0])
            context = x[:, -CONTEXT:]
        return probs

    def segments(self, pcm: np.ndarray, params: VadParams = VadParams()) -> list[Segment]:
        return segment_from_probs(self.probabilities(pcm), len(pcm), params)


def segment_from_probs(probs: np.ndarray, n_samples: int, p: VadParams) -> list[Segment]:
    """Ubah probabilitas per frame menjadi segmen, dengan potong paksa di titik paling sunyi."""
    frame_ms = FRAME * 1000 / SR
    redemption = max(1, round(p.redemption_ms / frame_ms))
    min_speech = max(1, round(p.min_speech_ms / frame_ms))
    max_frames = int(p.max_segment_s * 1000 / frame_ms)
    search = int(3000 / frame_ms)  # cari titik potong di 3 detik terakhir

    raw: list[tuple[int, int]] = []
    start = None
    silence = 0
    for i, pr in enumerate(probs):
        if start is None:
            if pr >= p.threshold:
                start, silence = i, 0
            continue
        if pr < p.neg_threshold:
            silence += 1
            if silence >= redemption:
                end = i - silence + 1
                if end - start >= min_speech:
                    raw.append((start, end))
                start, silence = None, 0
        else:
            silence = 0
        if start is not None and i - start + 1 >= max_frames:
            lo = max(start + 1, i - search)
            cut = lo + int(np.argmin(probs[lo:i + 1]))
            raw.append((start, cut))
            start, silence = cut, 0
    if start is not None and len(probs) - start >= min_speech:
        raw.append((start, len(probs)))

    pad = int(p.pad_ms * SR / 1000)
    out: list[Segment] = []
    for s, e in raw:
        a = max(0, s * FRAME - pad)
        b = min(n_samples, e * FRAME + pad)
        if out and a <= out[-1].end and (b - out[-1].start) / SR <= p.max_segment_s:
            out[-1] = Segment(out[-1].start, b)  # gabung segmen yang padding-nya bertumpuk
        elif out and a < out[-1].end:
            out.append(Segment(out[-1].end, b))  # jangan tumpang tindih
        else:
            out.append(Segment(a, b))
    return out


def pad_to_min(pcm: np.ndarray, min_s: float) -> np.ndarray:
    need = int(min_s * SR) - len(pcm)
    if need <= 0:
        return pcm
    return np.concatenate([pcm, np.zeros(need, dtype=np.float32)])
