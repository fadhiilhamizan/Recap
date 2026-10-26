"""Simulasi pipeline draf live (spike S5) dengan jam virtual.

Model antrean yang disimulasikan sama dengan desain ``recap-asr`` (dokumen 03 bagian 3.2 dan
dokumen 05 bagian 2.2):

  audio masuk real time -> VAD per frame 32 ms -> segmen ditutup (sunyi/redemption atau
  panjang maksimum) -> antrean -> SATU thread inferensi -> teks draf muncul.

Inferensi dijalankan sungguhan (waktu prosesnya diukur), tetapi audio tidak diputar real time:
waktu selesai tiap segmen dihitung sebagai ``max(waktu_segmen_ditutup, worker_bebas) + waktu_proses``.
Asumsinya beban capture/VAD diabaikan (VAD sekitar 0,3% dari durasi audio, diukur di S0).

Metrik:
- latensi = waktu teks muncul - akhir ucapan (detik, jam audio): p50, p95, maks
- backlog = antrean maksimum (detik audio yang menunggu) dan apakah tumbuh terus
- CPU = waktu CPU proses selama inferensi dibagi (durasi audio x jumlah core logis)
- WER draf (teks gabungan vs referensi gabungan)

  python -m recap_eval.live --manifest ../../.data/corpus/fleurs-id-long/manifest.jsonl \
      --engine-json '{...}' [--policy live|merge25]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil

from .audio import duration_s, load_audio
from .bench import DATA, machine_info
from .engines import EngineSpec, create_engine
from .manifest import load_manifest
from .metrics import ErrorCounts, score_item
from .vad import SR, SileroVad, VadParams, pad_to_min

POLICIES = {
    # Draf live sesuai dokumen 05: tutup segmen setelah 600 ms sunyi, maksimum 20 detik.
    "live": VadParams.live(),
    # Variasi: segmen ditutup lebih jarang (gabung mendekati 25 detik) untuk model Whisper.
    "merge25": VadParams(redemption_ms=600, pad_ms=200, max_segment_s=25.0),
}


def merge_segments(segs, max_s: float, max_gap_s: float = 2.0):
    """Gabungkan segmen berurutan sampai sekitar ``max_s`` (untuk kebijakan merge25)."""
    out = []
    for s in segs:
        if out and (s.end - out[-1][0]) / SR <= max_s and (s.start - out[-1][1]) / SR <= max_gap_s:
            out[-1] = (out[-1][0], s.end)
        else:
            out.append((s.start, s.end))
    return out


def percentile(xs, q):
    return float(np.percentile(xs, q)) if xs else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--engine-json", required=True)
    ap.add_argument("--policy", choices=sorted(POLICIES), default="live")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=DATA / "results-live")
    args = ap.parse_args(argv)

    spec = EngineSpec.from_dict(json.loads(args.engine_json))
    items = load_manifest(args.manifest)[: args.limit or None]
    params = POLICIES[args.policy]
    vad = SileroVad(DATA / "models" / "silero-vad" / "silero_vad.onnx")
    engine = create_engine(spec, DATA)
    proc_self = psutil.Process()
    n_cpu = psutil.cpu_count()

    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{spec.name}-{args.policy}"
    out_dir = args.out / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    latencies, queue_peaks, growth_flags = [], [], []
    totals = ErrorCounts()
    total_audio = cpu_used = 0.0
    seg_lengths = []
    rows = []
    for it in items:
        pcm = load_audio(it.audio)
        dur = duration_s(pcm)
        segs = vad.segments(pcm, params)
        spans = merge_segments(segs, 25.0) if args.policy == "merge25" else [(s.start, s.end) for s in segs]

        worker_free = 0.0
        texts = []
        seg_rows = []
        backlog_samples = []
        cpu0 = sum(proc_self.cpu_times()[:2])
        for a, b in spans:
            # Segmen baru bisa ditutup setelah sunyi sepanjang redemption sesudah akhir ucapan.
            # (Untuk potong paksa di panjang maksimum ini sedikit melebih-lebihkan latensi: konservatif.)
            close_t = min(b / SR - params.pad_ms / 1000 + params.redemption_ms / 1000, dur)
            res = engine.transcribe(pad_to_min(pcm[a:b], params.min_segment_s), it.language)
            start_t = max(close_t, worker_free)
            done_t = start_t + res.proc_s
            worker_free = done_t
            speech_end = b / SR - params.pad_ms / 1000
            latencies.append(done_t - speech_end)
            backlog_samples.append(start_t - close_t)  # lama segmen menunggu di antrean
            seg_lengths.append((b - a) / SR)
            texts.append(res.text.strip())
            seg_rows.append({"t0": round(a / SR, 2), "t1": round(b / SR, 2), "close": round(close_t, 2),
                             "done": round(done_t, 2), "proc": round(res.proc_s, 3), "text": res.text})
        cpu_used += sum(proc_self.cpu_times()[:2]) - cpu0
        total_audio += dur
        queue_peaks.append(max(backlog_samples) if backlog_samples else 0.0)
        # backlog "tumbuh terus" bila antrean di kuartal terakhir jauh lebih lama dari kuartal pertama
        q = max(1, len(backlog_samples) // 4)
        growth_flags.append(np.mean(backlog_samples[-q:]) > np.mean(backlog_samples[:q]) + 5.0)
        hyp = " ".join(t for t in texts if t)
        if it.ref:
            totals.add(score_item(it.ref, hyp))
        rows.append({"id": it.id, "dur_s": round(dur, 1), "n_segments": len(spans), "hyp": hyp, "segments": seg_rows})
        print(f"[{spec.name}/{args.policy}] {it.id}: {len(spans)} segmen, p95 latensi {percentile(latencies, 95):.1f} s", flush=True)

    engine.close()
    result = {
        "run_id": run_id, "engine": spec.__dict__, "policy": args.policy, "vad": params.__dict__,
        "machine": machine_info(), "audio_s": round(total_audio, 1), "segments": len(seg_lengths),
        "segment_len_mean_s": round(float(np.mean(seg_lengths)), 2) if seg_lengths else None,
        "latency_p50_s": round(percentile(latencies, 50), 2), "latency_p95_s": round(percentile(latencies, 95), 2),
        "latency_max_s": round(max(latencies), 2), "queue_wait_max_s": round(max(queue_peaks), 2),
        "backlog_growing": bool(any(growth_flags)),
        "cpu_share_of_machine": round(cpu_used / (total_audio * n_cpu), 3),
        "cpu_cores_equiv": round(cpu_used / total_audio, 2),
        "metrics": totals.as_dict(),
    }
    with (out_dir / "segments.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / "metrics.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    keys = ("latency_p50_s", "latency_p95_s", "latency_max_s", "queue_wait_max_s", "backlog_growing",
            "cpu_share_of_machine", "cpu_cores_equiv", "segment_len_mean_s")
    print(json.dumps({"run_id": run_id, **{k: result[k] for k in keys}, "wer": totals.wer}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
