"""Analisis rekaman spike S1: sinkronisasi mic vs system, celah, dan kelengkapan file.

  python scripts/s1_analyze.py <folder-rekaman>

Mengharapkan klik pendek (diputar ``s1-capture clicks`` dari proses terpisah) yang tertangkap di
kedua kanal: system (loopback) dan mic (lewat speaker laptop). Untuk tiap klik, onset di kedua
kanal dideteksi dan selisihnya dilaporkan dari waktu ke waktu. Drift = kemiringan selisih terhadap waktu.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48_000


def load_track(folder: Path, ch: str) -> np.ndarray:
    files = sorted((folder / "audio" / ch).glob("*.wav"))
    if not files:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate([sf.read(f, dtype="float32")[0] for f in files])


def onsets(x: np.ndarray, min_gap_s: float = 5.0) -> list[float]:
    """Onset klik: titik pertama energi pendek melewati ambang adaptif, dengan jarak minimal antar klik."""
    if len(x) == 0:
        return []
    win = int(0.002 * SR)
    env = np.sqrt(np.convolve(x.astype(np.float64) ** 2, np.ones(win) / win, mode="same"))
    thr = max(np.percentile(env, 99.5) * 0.5, 1e-4)
    out, last = [], -1e9
    idx = np.flatnonzero(env > thr)
    for i in idx:
        t = i / SR
        if t - last >= min_gap_s:
            out.append(t)
            last = t
    return out


def main(argv: list[str]) -> int:
    folder = Path(argv[1])
    mic, sys_ = load_track(folder, "mic"), load_track(folder, "system")
    print(f"durasi mic {len(mic) / SR:.1f} s, system {len(sys_) / SR:.1f} s, selisih panjang {abs(len(mic) - len(sys_)) / SR * 1000:.0f} ms")

    health = []
    for line in (folder / "timeline.jsonl").read_text(encoding="utf-8").splitlines():
        if '"gap"' not in line:
            continue
        try:
            health.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # baris terakhir terpotong setelah proses dibunuh: wajar, abaikan
    fill_min = SR // 50  # sama dengan GAP_FILL_MIN_FRAMES di s1-capture (20 ms)
    for ch in ("mic", "system"):
        rows = [h for h in health if h["ch"] == ch]
        filled = [h["gap"] for h in rows if h["gap"] > fill_min]
        jitter = [h["gap"] for h in rows if 0 < h["gap"] <= fill_min]
        disc = sum(h["disc"] for h in rows)
        print(f"{ch}: {len(rows)} paket, celah diisi {len(filled)} kali (maks {max(filled, default=0) / SR * 1000:.0f} ms), "
              f"jitter kecil tidak diisi {len(jitter)} kali (maks {max(jitter, default=0) / SR * 1000:.1f} ms), discontinuity {disc}")
    for ch, x in (("mic", mic), ("system", sys_)):
        rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0
        if rms < 1e-4:
            print(f"PERINGATAN: kanal {ch} nyaris hening total (RMS {20 * np.log10(rms + 1e-12):.0f} dBFS): "
                  "periksa mute/izin mikrofon. Recap harus mendeteksi ini dan memberi peringatan.")

    a, b = onsets(sys_), onsets(mic)
    pairs = []
    for t in a:
        near = [u for u in b if abs(u - t) < 1.0]
        if near:
            pairs.append((t, (near[0] - t) * 1000))
    if not pairs:
        print("Tidak ada pasangan klik terdeteksi (pastikan 'clicks' diputar lewat speaker, bukan headset).")
        return 1
    ts, offs = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    slope = np.polyfit(ts, offs, 1)[0] if len(ts) > 2 else 0.0
    print(f"{len(pairs)} klik berpasangan. Offset mic-system (ms): awal {offs[0]:.1f}, akhir {offs[-1]:.1f}, "
          f"rentang {offs.min():.1f}..{offs.max():.1f}, drift {slope * 3600:.1f} ms/jam")
    print("Catatan: offset konstan sekitar puluhan ms wajar (latensi speaker ke mic + buffer). Yang penting variasinya.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
