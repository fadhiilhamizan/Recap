"""Normalisasi teks untuk evaluasi STT Bahasa Indonesia, Inggris, dan campuran.

Aturan yang sama diterapkan ke referensi (gold) dan hipotesis agar WER adil:
- Unicode NFKC, huruf kecil.
- Anotasi non-ucapan dalam kurung siku, misalnya ``[tidak jelas]`` atau ``[tertawa]``, dibuang.
- Rentang bahasa Inggris di gold ditandai kurung kurawal, misalnya ``{stakeholder}``.
  Kurung dibuang dari teks, tetapi posisinya dicatat sebagai mask untuk CS-WER.
- Tanda hubung (``anak-anak``) diganti spasi, sehingga reduplikasi tetap konsisten.
- Angka ditulis ulang sebagai kata Bahasa Indonesia; ``%`` menjadi ``persen``.
- Tanda baca dibuang, spasi dirapikan.
- Kata pengisi (eh, em, hmm, ...) dibuang secara default.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

FILLERS = frozenset(
    {"eh", "ehm", "em", "emm", "hmm", "hm", "mm", "uh", "um", "umm", "ah", "eee", "ee", "erm"}
)

# Varian ejaan yang lazim (baku vs tidak baku). Keduanya dipetakan ke satu bentuk agar
# perbedaan ejaan tidak dihitung sebagai error pengenalan ucapan.
VARIANTS = {
    "mempengaruhi": "memengaruhi", "dipengaruhi": "dipengaruhi", "resiko": "risiko",
    "praktek": "praktik", "analisa": "analisis", "kwalitas": "kualitas", "nasehat": "nasihat",
    "ijin": "izin", "jadual": "jadwal", "aktifitas": "aktivitas", "efektifitas": "efektivitas",
    "obyek": "objek", "subyek": "subjek", "sistim": "sistem", "hutang": "utang", "okay": "oke",
    "ok": "oke", "silahkan": "silakan", "tehnik": "teknik", "tehnologi": "teknologi",
    "propinsi": "provinsi", "kwitansi": "kuitansi", "atlit": "atlet", "apotik": "apotek",
    "karir": "karier", "frekwensi": "frekuensi", "sekedar": "sekadar", "merubah": "mengubah",
}
# Gabungan yang sering ditulis terpisah atau tersambung; disamakan ke bentuk tersambung.
JOINS = {
    ("apa", "pun"): "apapun", ("siapa", "pun"): "siapapun", ("mana", "pun"): "manapun",
    ("kapan", "pun"): "kapanpun", ("walau", "pun"): "walaupun", ("sering", "kali"): "seringkali",
    ("meski", "pun"): "meskipun", ("bagaimana", "pun"): "bagaimanapun", ("dino", "saurus"): "dinosaurus",
}

_SATUAN = ["nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan"]
_SKALA = [(10**12, "triliun"), (10**9, "miliar"), (10**6, "juta"), (1000, "ribu")]

_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_PUNCT_RE = re.compile(r"[^\w\s{}]", re.UNICODE)


def angka_ke_kata(n: int) -> str:
    """Ubah bilangan bulat non-negatif menjadi kata Bahasa Indonesia."""
    if n < 0:
        return "minus " + angka_ke_kata(-n)
    if n < 10:
        return _SATUAN[n]
    if n < 20:
        if n == 10:
            return "sepuluh"
        if n == 11:
            return "sebelas"
        return _SATUAN[n - 10] + " belas"
    if n < 100:
        puluh, sisa = divmod(n, 10)
        teks = _SATUAN[puluh] + " puluh"
        return teks if sisa == 0 else teks + " " + angka_ke_kata(sisa)
    if n < 1000:
        ratus, sisa = divmod(n, 100)
        teks = "seratus" if ratus == 1 else _SATUAN[ratus] + " ratus"
        return teks if sisa == 0 else teks + " " + angka_ke_kata(sisa)
    for nilai, nama in _SKALA:
        if n >= nilai:
            depan, sisa = divmod(n, nilai)
            teks = "seribu" if (nilai == 1000 and depan == 1) else angka_ke_kata(depan) + " " + nama
            return teks if sisa == 0 else teks + " " + angka_ke_kata(sisa)
    raise ValueError(n)


def _ganti_angka(match: re.Match[str]) -> str:
    raw = match.group(0)
    # Konvensi Indonesia: titik = pemisah ribuan, koma = desimal.
    # "1.000.000" -> 1000000 ; "3,5" -> tiga koma lima ; "2.5" (gaya Inggris, satu titik, bukan 3 digit) -> dua koma lima
    if "," in raw:
        bulat, _, desimal = raw.replace(".", "").partition(",")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        bulat, desimal = raw.replace(".", ""), ""
    elif raw.count(".") == 1:
        bulat, _, desimal = raw.partition(".")
    else:
        bulat, desimal = raw.replace(".", ""), ""
    teks = angka_ke_kata(int(bulat)) if bulat else "nol"
    if desimal:
        teks += " koma " + " ".join(_SATUAN[int(d)] for d in desimal)
    return f" {teks} "


@dataclass(frozen=True)
class NormalizedText:
    tokens: list[str]
    english_mask: list[bool]

    @property
    def text(self) -> str:
        return " ".join(self.tokens)


def _canonicalize(tokens: list[str], mask: list[bool]) -> tuple[list[str], list[bool]]:
    out_t: list[str] = []
    out_m: list[bool] = []
    i = 0
    while i < len(tokens):
        pair = (tokens[i], tokens[i + 1]) if i + 1 < len(tokens) else None
        if pair in JOINS:
            out_t.append(JOINS[pair])
            out_m.append(mask[i] or mask[i + 1])
            i += 2
            continue
        out_t.append(VARIANTS.get(tokens[i], tokens[i]))
        out_m.append(mask[i])
        i += 1
    return out_t, out_m


def normalize(text: str, *, drop_fillers: bool = True, canonical: bool = True) -> NormalizedText:
    """Normalisasi teks dan kembalikan token beserta mask rentang Inggris (``{...}``).

    ``canonical`` menyamakan varian ejaan (``mempengaruhi`` = ``memengaruhi``) dan gabungan
    (``apa pun`` = ``apapun``). Matikan untuk WER "ketat".
    """
    t = unicodedata.normalize("NFKC", text).lower()
    t = _BRACKET_RE.sub(" ", t)
    t = t.replace("%", " persen ")
    t = _NUM_RE.sub(_ganti_angka, t)
    t = t.replace("-", " ").replace("_", " ")
    t = _PUNCT_RE.sub(" ", t)
    # Pisahkan kurung kurawal agar bisa dilacak sebagai penanda rentang.
    t = t.replace("{", " { ").replace("}", " } ")

    tokens: list[str] = []
    mask: list[bool] = []
    in_english = False
    for tok in t.split():
        if tok == "{":
            in_english = True
            continue
        if tok == "}":
            in_english = False
            continue
        if drop_fillers and tok in FILLERS:
            continue
        tokens.append(tok)
        mask.append(in_english)
    if canonical:
        tokens, mask = _canonicalize(tokens, mask)
    return NormalizedText(tokens, mask)


def normalize_text(text: str, *, drop_fillers: bool = True, canonical: bool = True) -> str:
    return normalize(text, drop_fillers=drop_fillers, canonical=canonical).text
