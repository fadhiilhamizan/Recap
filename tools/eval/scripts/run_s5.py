"""Jalankan matriks S5 (latensi draf live) secara berurutan; konfigurasi yang sudah selesai dilewati.

  python scripts/run_s5.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DATA = HERE.parents[1] / ".data"
MANIFEST = DATA / "corpus" / "fleurs-id-long" / "manifest.jsonl"

RUNS = [
    # (engine spec, policy)
    ({"name": "qwen3-0.6b-q8-cpu4", "kind": "transcribe_cpp", "model": "qwen3-asr-0.6b/Qwen3-ASR-0.6B-Q8_0.gguf", "backend": "cpu", "threads": 4}, "live"),
    ({"name": "qwen3-0.6b-q8-cpu2", "kind": "transcribe_cpp", "model": "qwen3-asr-0.6b/Qwen3-ASR-0.6B-Q8_0.gguf", "backend": "cpu", "threads": 2}, "live"),
    ({"name": "qwen3-0.6b-q8-vk", "kind": "transcribe_cpp", "model": "qwen3-asr-0.6b/Qwen3-ASR-0.6B-Q8_0.gguf", "backend": "vulkan"}, "live"),
    ({"name": "qwen3-1.7b-q5-vk", "kind": "transcribe_cpp", "model": "qwen3-asr-1.7b/Qwen3-ASR-1.7B-Q5_K_M.gguf", "backend": "vulkan"}, "live"),
    ({"name": "whisper-small-q8-cpu4", "kind": "transcribe_cpp", "model": "whisper-small/whisper-small-Q8_0.gguf", "backend": "cpu", "threads": 4}, "live"),
    ({"name": "whisper-turbo-q5-vk", "kind": "transcribe_cpp", "model": "whisper-large-v3-turbo/whisper-large-v3-turbo-Q5_K_M.gguf", "backend": "vulkan"}, "live"),
    ({"name": "whisper-turbo-q5-vk", "kind": "transcribe_cpp", "model": "whisper-large-v3-turbo/whisper-large-v3-turbo-Q5_K_M.gguf", "backend": "vulkan"}, "merge25"),
]


def main() -> int:
    out = DATA / "results-live"
    failures = []
    for spec, policy in RUNS:
        suffix = f"{spec['name']}-{policy}"
        done = [d for d in out.glob("*") if d.name[16:] == suffix and (d / "metrics.json").exists()] if out.exists() else []
        if done:
            print(f"SUDAH SELESAI {suffix}", flush=True)
            continue
        print(f"=== {suffix}", flush=True)
        rc = subprocess.call([sys.executable, "-u", "-m", "recap_eval.live", "--manifest", str(MANIFEST),
                              "--engine-json", json.dumps(spec), "--policy", policy], cwd=HERE)
        if rc:
            failures.append(suffix)
    print("S5 SELESAI" + (f"; GAGAL: {', '.join(failures)}" if failures else ""), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
