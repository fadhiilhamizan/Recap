"""Metrik STT: WER, CER, CS-WER (error pada token Inggris dalam transkrip Indonesia), dan halusinasi."""

from __future__ import annotations

from dataclasses import dataclass, field

import jiwer

from .normalize import normalize


@dataclass
class ErrorCounts:
    """Jumlah error yang bisa dijumlahkan lintas item (micro-average)."""

    ref_words: int = 0
    sub: int = 0
    dele: int = 0
    ins: int = 0
    ref_chars: int = 0
    char_errors: int = 0
    cs_ref_words: int = 0
    cs_errors: int = 0
    silence_minutes: float = 0.0
    silence_inserted_words: int = 0
    items: int = 0
    extra: dict = field(default_factory=dict)

    def add(self, other: "ErrorCounts") -> None:
        for name in (
            "ref_words", "sub", "dele", "ins", "ref_chars", "char_errors",
            "cs_ref_words", "cs_errors", "silence_minutes", "silence_inserted_words", "items",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def wer(self) -> float | None:
        return (self.sub + self.dele + self.ins) / self.ref_words if self.ref_words else None

    @property
    def cer(self) -> float | None:
        return self.char_errors / self.ref_chars if self.ref_chars else None

    @property
    def cs_wer(self) -> float | None:
        return self.cs_errors / self.cs_ref_words if self.cs_ref_words else None

    @property
    def hallucination_wpm(self) -> float | None:
        if self.silence_minutes <= 0:
            return None
        return self.silence_inserted_words / self.silence_minutes

    def as_dict(self) -> dict:
        return {
            "items": self.items,
            "ref_words": self.ref_words,
            "wer": self.wer,
            "cer": self.cer,
            "sub": self.sub,
            "del": self.dele,
            "ins": self.ins,
            "cs_ref_words": self.cs_ref_words,
            "cs_wer": self.cs_wer,
            "hallucination_wpm": self.hallucination_wpm,
        }


def score_item(reference: str, hypothesis: str, *, silence_minutes: float = 0.0) -> ErrorCounts:
    """Hitung error satu item.

    Bila referensi kosong setelah normalisasi (bagian hening atau tanpa ucapan), semua kata
    hipotesis dihitung sebagai kata halusinasi per menit hening, bukan sebagai WER.
    """
    ref = normalize(reference)
    hyp = normalize(hypothesis)
    out = ErrorCounts(items=1)

    if not ref.tokens:
        out.silence_minutes = silence_minutes
        out.silence_inserted_words = len(hyp.tokens)
        return out

    ref_text, hyp_text = ref.text, hyp.text
    words = jiwer.process_words(ref_text, hyp_text if hyp.tokens else "")
    out.ref_words = len(ref.tokens)
    out.sub, out.dele, out.ins = words.substitutions, words.deletions, words.insertions

    chars = jiwer.process_characters(ref_text, hyp_text if hyp.tokens else "")
    out.ref_chars = len(ref_text)
    out.char_errors = chars.substitutions + chars.deletions + chars.insertions

    if any(ref.english_mask):
        out.cs_ref_words = sum(ref.english_mask)
        out.cs_errors = _cs_errors(words.alignments[0], ref.english_mask)
    return out


def _cs_errors(alignment, mask: list[bool]) -> int:
    """Hitung error pada token referensi yang ditandai Inggris.

    Substitusi dan deletion dihitung pada posisi bertanda. Insertion dihitung bila
    bersebelahan dengan token bertanda (di dalam atau di tepi rentang Inggris).
    """
    errors = 0
    for chunk in alignment:
        if chunk.type in ("substitute", "delete"):
            errors += sum(mask[i] for i in range(chunk.ref_start_idx, chunk.ref_end_idx))
        elif chunk.type == "insert":
            pos = chunk.ref_start_idx
            left = mask[pos - 1] if pos - 1 >= 0 else False
            right = mask[pos] if pos < len(mask) else False
            if left or right:
                errors += chunk.hyp_end_idx - chunk.hyp_start_idx
    return errors
