"""Gabungkan semua ``.data/results/*/metrics.json`` menjadi tabel Markdown.

  python -m recap_eval.report                 # cetak ke stdout
  python -m recap_eval.report --out ../../docs/spikes/S4-hasil.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bench import DATA


def _pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def build_table(results: list[dict], set_filter: str | None = None) -> str:
    rows = [
        "| Run | Engine / model | Backend | Thread | Bahasa | Set | Item | WER | CER | CS-WER | Kecepatan (x real time) | RTF | Puncak RAM (MB) | Load (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: (r["engine"]["name"], r["run_id"])):
        e = r["engine"]
        sets = r["metrics_per_set"] if set_filter is None else {k: v for k, v in r["metrics_per_set"].items() if k == set_filter}
        for set_name, m in sets.items():
            rows.append(
                f"| {r['run_id']} | {e['name']} (`{Path(e['model']).name}`) | {e['backend']} | {e['threads'] or 'default'} "
                f"| {e['language_mode']} | {set_name} | {m['items']} | {_pct(m['wer'])} | {_pct(m['cer'])} | {_pct(m['cs_wer'])} "
                f"| {r['speed_x_realtime']} | {r['rtf']} | {r['peak_mem_mb']} | {r['load_s']} |"
            )
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=DATA / "results")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--set", dest="set_filter")
    args = ap.parse_args(argv)

    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.results.glob("*/metrics.json"))]
    if not results:
        print("Belum ada hasil.")
        return 1
    md = build_table(results, args.set_filter)
    machine = results[-1]["machine"]
    header = (
        f"Mesin: {machine['processor']} ({machine['cpu_count_physical']} core / {machine['cpu_count_logical']} thread), "
        f"RAM {machine['ram_gb']} GB, {machine['platform']}. transcribe.cpp {machine['transcribe_cpp']}.\n\n"
    )
    text = header + md + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Ditulis ke {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
