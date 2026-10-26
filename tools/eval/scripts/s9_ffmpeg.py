"""Spike S9: decode beragam format file import dengan ffmpeg LGPL (sidecar).

  python scripts/s9_ffmpeg.py

1. Membuat 15 file uji dari audio FLEURS (format umum, WhatsApp Opus, video, file 3 jam,
   file rusak, video tanpa audio) dengan encoder yang tersedia di build LGPL.
2. Untuk tiap file: ``ffprobe`` (durasi, stream audio), lalu decode ke WAV 16 kHz mono
   persis seperti yang akan dilakukan ``recap-app`` (argumen sebagai array, tanpa shell).
3. Memeriksa durasi hasil decode dan kemiripan sinyal terhadap sumber (korelasi pada sampel
   yang diselaraskan), lalu menulis laporan Markdown.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / ".data"
FF = DATA / "bin" / "ffmpeg"
FFMPEG, FFPROBE = str(FF / "ffmpeg.exe"), str(FF / "ffprobe.exe")
WORK = DATA / "s9"
SRC_DIR = DATA / "corpus" / "fleurs-id" / "audio"
REPORT = ROOT / "docs" / "spikes" / "S9-ffmpeg.md"


def ff(*args: str, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def make_samples() -> list[dict]:
    WORK.mkdir(parents=True, exist_ok=True)
    srcs = sorted(SRC_DIR.glob("*.wav"))[:6]
    # Sumber: 6 kalimat disambung (sekitar 1 menit), 16 kHz mono
    concat = WORK / "source.wav"
    data = np.concatenate([sf.read(s, dtype="float32")[0] for s in srcs])
    sf.write(concat, data, 16000, subtype="PCM_16")
    src = str(concat)
    lavfi_video = ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=25"]
    specs = [
        ("mp3", "rapat.mp3", ["-i", src, "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k"]),
        ("m4a-aac", "rapat.m4a", ["-i", src, "-ar", "48000", "-c:a", "aac", "-b:a", "96k"]),
        ("wav-24bit-48k-stereo", "rapat-24bit.wav", ["-i", src, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le"]),
        ("flac", "rapat.flac", ["-i", src, "-c:a", "flac"]),
        ("ogg-vorbis", "rapat.ogg", ["-i", src, "-c:a", "libvorbis", "-q:a", "4"]),
        ("opus-whatsapp", "PTT-20261010-WA0001.opus", ["-i", src, "-ar", "16000", "-ac", "1", "-c:a", "libopus",
                                                       "-b:a", "16k", "-application", "voip", "-f", "ogg"]),
        ("mp4-h264-aac", "zoom-rekaman.mp4", [*lavfi_video, "-i", src, "-shortest", "-c:v", "libopenh264",
                                              "-b:v", "500k", "-c:a", "aac", "-b:a", "128k", "-ar", "48000"]),
        ("mkv-vp9-opus", "meet-rekaman.mkv", [*lavfi_video, "-i", src, "-shortest", "-c:v", "libvpx-vp9",
                                              "-deadline", "realtime", "-b:v", "300k", "-c:a", "libopus", "-b:a", "64k"]),
        ("webm-vp8-vorbis", "rekaman.webm", [*lavfi_video, "-i", src, "-shortest", "-c:v", "libvpx",
                                             "-deadline", "realtime", "-b:v", "300k", "-c:a", "libvorbis"]),
        ("mov-iphone-aac", "IMG_0042.mov", [*lavfi_video, "-i", src, "-shortest", "-c:v", "mpeg4",
                                            "-c:a", "aac", "-ar", "44100", "-ac", "2"]),
        ("wma", "rapat.wma", ["-i", src, "-c:a", "wmav2", "-b:a", "64k"]),
        ("amr-nb", "rekaman.amr", ["-i", src, "-ar", "8000", "-ac", "1", "-c:a", "libopencore_amrnb", "-b:a", "12.2k"]),
        ("3jam-m4a", "seminar-3jam.m4a", ["-stream_loop", "179", "-i", src, "-c:a", "aac", "-b:a", "48k", "-ac", "1"]),
    ]
    samples = []
    for kind, name, args in specs:
        out = WORK / name
        r = ff(*args, str(out), timeout=1800)
        samples.append({"kind": kind, "file": out, "valid": True, "made": r.returncode == 0,
                        "make_err": r.stderr.strip()[-300:]})
    # MP3 terpotong (unduhan putus) + sampah di awal: harus diselamatkan sepanjang bagian yang tersisa.
    cut = WORK / "terpotong.mp3"
    raw = (WORK / "rapat.mp3").read_bytes()
    cut.write_bytes(b"\x00garbage\xff" * 50 + raw[: len(raw) // 3])
    samples.append({"kind": "mp3-terpotong", "file": cut, "valid": True, "salvage": True, "made": True, "make_err": ""})
    # Bukan file media sama sekali (sampah berekstensi .mp3): harus ditolak.
    junk = WORK / "bukan-audio.mp3"
    junk.write_bytes(np.random.default_rng(1).integers(0, 256, 200_000, dtype=np.uint8).tobytes())
    samples.append({"kind": "sampah-ekstensi-mp3", "file": junk, "valid": False, "made": True, "make_err": ""})
    novid = WORK / "video-tanpa-audio.mp4"
    r = ff(*lavfi_video, "-t", "10", "-c:v", "libopenh264", str(novid))
    samples.append({"kind": "video-tanpa-audio", "file": novid, "valid": False, "made": r.returncode == 0,
                    "make_err": r.stderr.strip()[-300:]})
    return samples


def probe(path: Path) -> dict:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name",
                        "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return {"ok": False, "err": r.stderr.strip()[-200:]}
    d = json.loads(r.stdout or "{}")
    audio = [s["codec_name"] for s in d.get("streams", []) if s.get("codec_type") == "audio"]
    return {"ok": True, "duration": float(d.get("format", {}).get("duration", 0) or 0), "audio_codecs": audio}


def decode(path: Path) -> tuple[bool, Path, float, str]:
    out = path.with_suffix(".decoded16k.wav")
    t0 = time.perf_counter()
    # Pilih stream audio pertama secara eksplisit; gagal bila tidak ada audio.
    r = ff("-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out), timeout=1800)
    return r.returncode == 0 and out.exists(), out, time.perf_counter() - t0, r.stderr.strip()[-200:]


def similarity(decoded: Path, reference: np.ndarray) -> float | None:
    """Korelasi maksimum (setelah penyelarasan kasar) pada 20 detik pertama, mengabaikan delay encoder."""
    x = sf.read(decoded, dtype="float32")[0]
    n = min(len(x), len(reference), 16000 * 20)
    if n < 16000:
        return None
    a, b = x[: n + 4000], reference[:n]
    best = 0.0
    for lag in range(0, 4000, 8):  # sampai 250 ms (priming encoder/frame AAC dan MP3)
        seg = a[lag:lag + n]
        if len(seg) < n:
            break
        c = float(np.dot(seg, b) / (np.linalg.norm(seg) * np.linalg.norm(b) + 1e-9))
        best = max(best, c)
    return best


class SttCheck:
    """Bandingkan WER STT hasil decode dengan WER audio sumber (Qwen3-ASR-0.6B, CPU)."""

    def __init__(self, source_files: list[Path]):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import transcribe_cpp
        from recap_eval.manifest import load_manifest
        from recap_eval.metrics import score_item

        self.score_item = score_item
        refs = {it.audio.name: it.ref for it in load_manifest(DATA / "corpus" / "fleurs-id" / "manifest.jsonl")}
        self.ref = " ".join(refs[f.name] for f in source_files)
        self.model = transcribe_cpp.Model(str(DATA / "models" / "qwen3-asr-0.6b" / "Qwen3-ASR-0.6B-Q8_0.gguf"), backend="cpu")
        self.session = self.model.session()

    def wer(self, wav: Path) -> float:
        pcm = sf.read(wav, dtype="float32")[0]
        text = self.session.run(pcm, language="id", timestamps="none").text
        return self.score_item(self.ref, text).wer


def main() -> int:
    if not Path(FFMPEG).exists():
        print("ffmpeg belum diunduh: python scripts/download_models.py --groups s9", file=sys.stderr)
        return 2
    samples = make_samples()
    reference = sf.read(WORK / "source.wav", dtype="float32")[0]
    src_dur = len(reference) / 16000
    stt = SttCheck(sorted(SRC_DIR.glob("*.wav"))[:6])
    base_wer = stt.wer(WORK / "source.wav")
    print(f"WER STT audio sumber: {base_wer:.3f}")
    rows = []
    for s in samples:
        p = probe(s["file"]) if s["made"] else {"ok": False, "err": "gagal dibuat: " + s["make_err"]}
        ok, out, secs, err = decode(s["file"]) if s["made"] else (False, None, 0.0, "")
        dur = sf.info(out).duration if ok else None
        long_file = s["kind"].startswith("3jam")
        salvage = s.get("salvage", False)
        expect = src_dur * 180 if long_file else (p.get("duration") if salvage else src_dur)
        sim = similarity(out, reference) if ok and not long_file and not salvage else None
        wer = stt.wer(out) if ok and not long_file and not salvage else None
        # Codec telepon (AMR 8 kHz) dan Opus 16 kbps boleh sedikit lebih buruk dari sumber.
        tol = 0.10 if s["kind"] in ("amr-nb",) else 0.05
        if s["valid"]:
            passed = ok and dur is not None and expect is not None and abs(dur - expect) <= 0.5 \
                and (wer is None or wer <= base_wer + tol)
        else:
            passed = not ok  # bukan media: harus ditolak dengan error, bukan menghasilkan audio palsu
        rows.append({"kind": s["kind"], "file": s["file"].name, "valid": s["valid"],
                     "codecs": ",".join(p.get("audio_codecs", [])) if p.get("ok") else "-",
                     "probe_dur": round(p.get("duration", 0), 1) if p.get("ok") else None,
                     "decoded_dur": round(dur, 1) if dur else None, "expected_dur": round(expect, 1) if expect else None,
                     "similarity": round(sim, 3) if sim is not None else None,
                     "wer": round(wer * 100, 1) if wer is not None else None,
                     "decode_s": round(secs, 2), "passed": passed, "error": (err or p.get("err", ""))[:120]})
        print(f"{'LULUS' if passed else 'GAGAL'}  {s['kind']:<22} decode {secs:6.2f} s  dur {dur}  WER {wer}", flush=True)

    version = subprocess.run([FFMPEG, "-hide_banner", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    lines = [
        "# S9. Hasil Decode File Import dengan ffmpeg LGPL",
        "",
        f"Dijalankan: {time.strftime('%Y-%m-%d %H:%M')} · {version}",
        "Build: BtbN/FFmpeg-Builds `ffmpeg-n9.0-latest-win64-lgpl-shared-9.0` (tanpa `--enable-gpl`/`--enable-nonfree`; "
        "berlisensi LGPL v3 karena `--enable-version3` untuk opencore-amr).",
        "",
        "Perintah decode (sama dengan rencana `recap-app`): `ffmpeg -i <file> -map 0:a:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le out.wav`.",
        "Lulus untuk file valid: decode sukses, durasi selisih 0,5 detik atau kurang, dan **WER STT (Qwen3-ASR-0.6B) hasil decode "
        f"tidak lebih dari 5 poin di atas WER audio sumber** ({base_wer * 100:.1f}%; AMR 8 kHz diberi toleransi 10 poin). "
        "File terpotong lulus bila bagian yang tersisa terbaca utuh. File bukan media lulus bila ditolak dengan error.",
        "Kolom kemiripan (korelasi sampel) hanya informasi: rendah untuk codec lossy bitrate rendah walau isinya terbaca.",
        "",
        "| Jenis | File | Valid | Codec audio | Durasi probe (s) | Durasi decode (s) | Harapan (s) | WER STT (%) | Kemiripan | Waktu decode (s) | Hasil | Error |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['kind']} | `{r['file']}` | {'ya' if r['valid'] else 'tidak'} | {r['codecs']} | {r['probe_dur']} "
                     f"| {r['decoded_dur']} | {r['expected_dur']} | {r['wer']} | {r['similarity']} | {r['decode_s']} "
                     f"| {'**Lulus**' if r['passed'] else '**Gagal**'} | {r['error'].replace('|', '/') if not r['passed'] or not r['valid'] else ''} |")
    n_valid = sum(r["valid"] for r in rows)
    n_ok = sum(r["passed"] and r["valid"] for r in rows)
    n_rej = sum(r["passed"] and not r["valid"] for r in rows)
    lines += ["", f"**Ringkasan:** {n_ok}/{n_valid} file valid lulus; {n_rej}/{len(rows) - n_valid} file tidak valid ditolak dengan benar."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Laporan: {REPORT}")
    return 0 if n_ok == n_valid and n_rej == len(rows) - n_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
