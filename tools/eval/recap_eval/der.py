"""Diarization Error Rate (DER) berbasis frame, untuk spike S7.

Input: daftar giliran ``(start_s, end_s, speaker)`` untuk referensi dan hipotesis
(bisa dibaca dari file RTTM). Pemetaan speaker hipotesis ke referensi memakai
Hungarian (``scipy.optimize.linear_sum_assignment``). Collar di sekitar batas
giliran referensi diabaikan (default 0,25 detik, konvensi umum).
Overlap ditangani: setiap frame bisa punya lebih dari satu speaker.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

Turn = tuple[float, float, str]


def read_rttm(path: str | Path) -> list[Turn]:
    turns: list[Turn] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0] == "SPEAKER":
            start, dur, spk = float(parts[3]), float(parts[4]), parts[7]
            turns.append((start, start + dur, spk))
    return turns


def _matrix(turns: list[Turn], n: int, step: float) -> tuple[np.ndarray, list[str]]:
    speakers = sorted({t[2] for t in turns})
    m = np.zeros((len(speakers), n), dtype=bool)
    for s, e, spk in turns:
        m[speakers.index(spk), int(round(s / step)):int(round(e / step))] = True
    return m, speakers


def der(reference: list[Turn], hypothesis: list[Turn], *, collar: float = 0.25, step: float = 0.01) -> dict:
    end = max([t[1] for t in reference + hypothesis] + [0.0])
    n = int(np.ceil(end / step)) + 1
    ref, _ = _matrix(reference, n, step)
    hyp, _ = _matrix(hypothesis, n, step)

    scored = np.ones(n, dtype=bool)
    if collar > 0:
        c = int(round(collar / step))
        for s, e, _spk in reference:
            for b in (int(round(s / step)), int(round(e / step))):
                scored[max(0, b - c):min(n, b + c)] = False

    ref, hyp = ref[:, scored], hyp[:, scored]
    n_ref = ref.sum(axis=0)
    n_hyp = hyp.sum(axis=0)
    total = int(n_ref.sum())

    # Pemetaan optimal speaker hipotesis -> referensi (maksimalkan waktu yang cocok)
    if ref.shape[0] and hyp.shape[0]:
        overlap = ref.astype(np.int32) @ hyp.astype(np.int32).T
        r_idx, h_idx = linear_sum_assignment(-overlap)
        mapped = int(overlap[r_idx, h_idx].sum())
    else:
        mapped = 0

    miss = int(np.maximum(n_ref - n_hyp, 0).sum())
    false_alarm = int(np.maximum(n_hyp - n_ref, 0).sum())
    confusion = int(np.minimum(n_ref, n_hyp).sum()) - mapped
    return {
        "der": (miss + false_alarm + confusion) / total if total else None,
        "miss": miss * step,
        "false_alarm": false_alarm * step,
        "confusion": confusion * step,
        "scored_speech_s": total * step,
    }
