"""Siapkan subset FLEURS Bahasa Indonesia (test split, CC-BY-4.0) sebagai korpus pembanding.

  python scripts/prepare_fleurs.py --count 200

Hasil: ``.data/corpus/fleurs-id/{audio/*.wav, manifest.jsonl}``. Arsip tar dihapus setelah
ekstraksi kecuali ``--keep-archive``. Pemilihan item deterministik (diurutkan berdasarkan id,
lalu diambil dengan langkah tetap) agar hasil antar mesin bisa dibandingkan.
"""

from __future__ import annotations

import argparse
import csv
import json
import tarfile
from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / ".data" / "corpus" / "fleurs-id"
REPO = "google/fleurs"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--keep-archive", action="store_true")
    args = ap.parse_args(argv)

    cache = ROOT / ".data" / "cache"
    tsv = Path(hf_hub_download(REPO, f"data/id_id/{args.split}.tsv", repo_type="dataset", local_dir=cache))
    rows = {}
    with tsv.open(encoding="utf-8") as fh:
        for r in csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            # kolom: id, nama file, transkripsi mentah, transkripsi ternormalisasi, fonem, jumlah sample, gender
            rows.setdefault(r[1], r)
    names = sorted(rows)
    step = max(1, len(names) // args.count)
    chosen = names[::step][: args.count]
    print(f"{len(rows)} utterance di split {args.split}; memilih {len(chosen)}")

    archive = Path(hf_hub_download(REPO, f"data/id_id/audio/{args.split}.tar.gz", repo_type="dataset", local_dir=cache))
    audio_dir = OUT / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(chosen)
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            name = Path(member.name).name
            if member.isfile() and name in wanted:
                with tf.extractfile(member) as src:
                    (audio_dir / name).write_bytes(src.read())

    with (OUT / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for i, name in enumerate(chosen):
            r = rows[name]
            if not (audio_dir / name).exists():
                continue
            fh.write(json.dumps({
                "id": f"fleurs-id-{args.split}-{i:04d}", "set": "fleurs-id", "audio": f"audio/{name}",
                "ref": r[2], "language": "id", "kind": "utterance",
                "consent": "public-cc-by-4.0 (google/fleurs)", "source_id": r[0],
            }, ensure_ascii=False) + "\n")
    if not args.keep_archive:
        archive.unlink(missing_ok=True)
    print(f"Manifest: {OUT / 'manifest.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
