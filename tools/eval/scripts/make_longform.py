"""Buat aliran audio panjang dari kalimat FLEURS untuk uji pipeline live (S5) dan VAD long-form.

  python scripts/make_longform.py --minutes 10 --streams 4

Kalimat disambung dengan jeda acak (deterministik, seed tetap): kebanyakan 0,2 sampai 2,5 detik,
sesekali jeda panjang 5 sampai 8 detik. Hasil: ``.data/corpus/fleurs-id-long/`` berisi WAV,
``manifest.jsonl`` (kind=longform), dan ``<id>.utts.json`` (batas waktu tiap kalimat untuk
menghitung latensi).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recap_eval.audio import SAMPLE_RATE, load_audio, save_wav  # noqa: E402
from recap_eval.manifest import load_manifest  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / ".data" / "corpus" / "fleurs-id" / "manifest.jsonl"
OUT = ROOT / ".data" / "corpus" / "fleurs-id-long"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--streams", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261010)
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    items = load_manifest(SRC)
    (OUT / "audio").mkdir(parents=True, exist_ok=True)
    manifest = []
    idx = 0
    for s in range(args.streams):
        pieces, utts, refs = [], [], []
        t = rng.uniform(0.5, 1.5)
        pieces.append(np.zeros(int(t * SAMPLE_RATE), dtype=np.float32))
        while t < args.minutes * 60 and idx < len(items):
            it = items[idx]
            idx += 1
            pcm = load_audio(it.audio)
            start = t
            t += len(pcm) / SAMPLE_RATE
            utts.append({"id": it.id, "start": round(start, 3), "end": round(t, 3)})
            refs.append(it.ref)
            pieces.append(pcm)
            gap = rng.uniform(5, 8) if rng.random() < 0.08 else rng.uniform(0.2, 2.5)
            pieces.append(np.zeros(int(gap * SAMPLE_RATE), dtype=np.float32))
            t += gap
        sid = f"fleurs-id-long-{s:02d}"
        save_wav(OUT / "audio" / f"{sid}.wav", np.concatenate(pieces))
        (OUT / f"{sid}.utts.json").write_text(json.dumps(utts, ensure_ascii=False, indent=1), encoding="utf-8")
        manifest.append({"id": sid, "set": "fleurs-id-long", "audio": f"audio/{sid}.wav", "ref": " ".join(refs),
                         "language": "id", "kind": "longform", "consent": "public-cc-by-4.0 (google/fleurs)",
                         "utts_file": f"{sid}.utts.json", "duration_s": round(t, 1), "n_utts": len(utts)})
        print(f"{sid}: {t / 60:.1f} menit, {len(utts)} kalimat")
    with (OUT / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for m in manifest:
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
