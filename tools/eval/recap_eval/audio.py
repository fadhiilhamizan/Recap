"""Muat audio apa pun (via PyAV/FFmpeg) menjadi PCM float32 mono 16 kHz."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import soundfile as sf

SAMPLE_RATE = 16_000


def load_audio(path: str | Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Dekode file audio/video ke float32 mono pada ``sample_rate``.

    Resampling memakai resampler FFmpeg (swresample), bukan decimation kasar.
    """
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError(f"Tidak ada stream audio di {path}")
        resampler = av.AudioResampler(format="flt", layout="mono", rate=sample_rate)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32, copy=False)


def save_wav(path: str | Path, pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    sf.write(str(path), pcm, sample_rate, subtype="PCM_16")


def duration_s(pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    return len(pcm) / sample_rate
