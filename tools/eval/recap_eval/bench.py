"""Jalankan satu konfigurasi engine pada satu manifest dan simpan hipotesis + metrik.

Contoh:
  python -m recap_eval.bench --manifest ../../.data/corpus/fleurs-id/manifest.jsonl \
      --engine-json '{"name":"qwen3-0.6b-q8-cpu4","kind":"transcribe_cpp","model":"qwen3-asr-0.6b/Qwen3-ASR-0.6B-Q8_0.gguf","backend":"cpu","threads":4}'

Satu konfigurasi per proses, agar puncak memori (peak working set) terukur bersih.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .audio import duration_s, load_audio
from .engines import EngineSpec, create_engine
from .manifest import load_manifest
from .metrics import ErrorCounts, score_item
from .vad import SileroVad, VadParams, pad_to_min

ROOT = Path(__file__).resolve().parents[3]  # root repo Recap
DATA = ROOT / ".data"


def machine_info() -> dict:
    import transcribe_cpp

    info = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count_logical": psutil.cpu_count(),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "python": sys.version.split()[0],
        "transcribe_cpp": getattr(transcribe_cpp, "native_version", lambda: "?")(),
    }
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--engine-json", help="EngineSpec sebagai JSON")
    ap.add_argument("--engine-file", type=Path, help="file JSON berisi EngineSpec")
    ap.add_argument("--mode", choices=["auto", "utterance", "vad"], default="auto",
                    help="auto: item 'longform' disegmentasi VAD, 'utterance' dikirim utuh")
    ap.add_argument("--vad-profile", choices=["final", "live"], default="final")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sets", default="", help="filter set, dipisah koma")
    ap.add_argument("--out", type=Path, default=DATA / "results")
    ap.add_argument("--tag", default="", help="label tambahan untuk run (misalnya nama mesin)")
    args = ap.parse_args(argv)

    spec_dict = json.loads(args.engine_json) if args.engine_json else json.loads(args.engine_file.read_text(encoding="utf-8"))
    spec = EngineSpec.from_dict(spec_dict)

    items = load_manifest(args.manifest)
    if args.sets:
        wanted = set(args.sets.split(","))
        items = [it for it in items if it.set in wanted]
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("Tidak ada item untuk dijalankan.", file=sys.stderr)
        return 2

    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{spec.name}" + (f"-{args.tag}" if args.tag else "")
    out_dir = args.out / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    vad = None
    vad_params = VadParams.live() if args.vad_profile == "live" else VadParams()
    if args.mode != "utterance" and any(it.kind == "longform" for it in items) or args.mode == "vad":
        vad = SileroVad(DATA / "models" / "silero-vad" / "silero_vad.onnx")

    print(f"[{spec.name}] memuat model...", flush=True)
    engine = create_engine(spec, DATA)
    print(f"[{spec.name}] load {engine.load_s:.1f} s; {len(items)} item", flush=True)

    totals = ErrorCounts()
    per_set: dict[str, ErrorCounts] = defaultdict(ErrorCounts)
    total_audio = total_proc = 0.0
    notes: set[str] = set()
    t_start = time.perf_counter()

    with (out_dir / "hyp.jsonl").open("w", encoding="utf-8") as hyp_fh:
        for n, it in enumerate(items, 1):
            pcm = load_audio(it.audio)
            dur = duration_s(pcm)
            use_vad = args.mode == "vad" or (args.mode == "auto" and it.kind == "longform")
            if use_vad:
                segs = vad.segments(pcm, vad_params)
                pieces = [(s.start_s, s.end_s, pcm[s.start:s.end]) for s in segs]
            else:
                pieces = [(0.0, dur, pcm)]

            texts, proc = [], 0.0
            seg_out = []
            for t0, t1, chunk in pieces:
                res = engine.transcribe(pad_to_min(chunk, vad_params.min_segment_s), it.language)
                proc += res.proc_s
                if res.note:
                    notes.add(res.note)
                if res.text.strip():
                    texts.append(res.text.strip())
                seg_out.append({"t0": round(t0, 2), "t1": round(t1, 2), "text": res.text, "lang": res.language})
            hyp = " ".join(texts)

            silence_min = dur / 60 if it.set == "silence" else 0.0
            if it.ref is not None:
                counts = score_item(it.ref, hyp, silence_minutes=silence_min)
                totals.add(counts)
                per_set[it.set].add(counts)
            total_audio += dur
            total_proc += proc
            hyp_fh.write(json.dumps({
                "id": it.id, "set": it.set, "dur_s": round(dur, 2), "proc_s": round(proc, 3),
                "rtf": round(proc / dur, 4) if dur else None, "hyp": hyp, "ref": it.ref,
                "segments": seg_out if use_vad else None,
            }, ensure_ascii=False) + "\n")
            if n % 10 == 0 or n == len(items):
                wer = totals.wer
                print(f"[{spec.name}] {n}/{len(items)}  WER sementara {wer:.3f}" if wer is not None else f"[{spec.name}] {n}/{len(items)}", flush=True)

    mem = psutil.Process().memory_info()
    peak_bytes = getattr(mem, "peak_wset", None) or mem.rss
    if engine.peak_child_rss:
        peak_bytes = engine.peak_child_rss
    engine.close()

    result = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "manifest": str(args.manifest),
        "mode": args.mode,
        "vad_profile": args.vad_profile if vad else None,
        "engine": spec.__dict__,
        "machine": machine_info(),
        "tag": args.tag,
        "load_s": round(engine.load_s, 2),
        "audio_s": round(total_audio, 1),
        "proc_s": round(total_proc, 1),
        "rtf": round(total_proc / total_audio, 4) if total_audio else None,
        "speed_x_realtime": round(total_audio / total_proc, 2) if total_proc else None,
        "peak_mem_mb": round(peak_bytes / 2**20),
        "wall_s": round(time.perf_counter() - t_start, 1),
        "notes": sorted(notes),
        "metrics": totals.as_dict(),
        "metrics_per_set": {k: v.as_dict() for k, v in sorted(per_set.items())},
    }
    (out_dir / "metrics.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    m = result["metrics"]
    print(json.dumps({k: result[k] for k in ("run_id", "rtf", "speed_x_realtime", "peak_mem_mb")} | {"wer": m["wer"], "cer": m["cer"], "cs_wer": m["cs_wer"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
