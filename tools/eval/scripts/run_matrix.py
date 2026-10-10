"""Jalankan seluruh matriks engine (satu proses per konfigurasi) lalu tulis laporan.

Konfigurasi yang sudah punya ``metrics.json`` dilewati; run yang terputus dilanjutkan
(``--fresh`` untuk mengulang semuanya).

  python scripts/run_matrix.py --manifest ../../.data/corpus/fleurs-id/manifest.jsonl --limit 50
  python scripts/run_matrix.py --manifest ... --only qwen3-0.6b-q8-cpu4,whisper-turbo-q5-vk

Konfigurasi yang file modelnya belum ada akan dilewati (dengan pesan).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
DATA = ROOT / ".data"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--matrix", type=Path, default=HERE / "configs" / "s4_matrix.json")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sets", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--mode", default="auto")
    ap.add_argument("--fresh", action="store_true", help="jangan lewati/lanjutkan run sebelumnya")
    args = ap.parse_args(argv)

    engines = json.loads(args.matrix.read_text(encoding="utf-8"))["engines"]
    only = set(filter(None, args.only.split(",")))
    failures = []
    for spec in engines:
        if only and spec["name"] not in only:
            continue
        if not (DATA / "models" / spec["model"]).exists():
            print(f"LEWATI {spec['name']}: model {spec['model']} belum diunduh")
            continue
        suffix = spec["name"] + (f"-{args.tag}" if args.tag else "")
        previous = sorted(d for d in (DATA / "results").glob("*") if d.is_dir() and d.name[16:] == suffix)
        resume = None
        if previous and not args.fresh:
            last = previous[-1]
            if (last / "metrics.json").exists():
                print(f"SUDAH SELESAI {spec['name']}: {last.name}", flush=True)
                continue
            if (last / "hyp.jsonl").exists():
                resume = last
        cmd = [sys.executable, "-m", "recap_eval.bench", "--manifest", str(args.manifest),
               "--engine-json", json.dumps(spec), "--mode", args.mode]
        if resume:
            cmd += ["--resume", str(resume)]
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        if args.sets:
            cmd += ["--sets", args.sets]
        if args.tag:
            cmd += ["--tag", args.tag]
        print(f"=== {spec['name']}", flush=True)
        rc = subprocess.call(cmd, cwd=HERE)
        if rc != 0:
            failures.append(spec["name"])
    subprocess.call([sys.executable, "-m", "recap_eval.report"], cwd=HERE)
    if failures:
        print("GAGAL:", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
