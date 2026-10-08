import numpy as np
import pytest

from recap_eval.der import der
from recap_eval.metrics import score_item
from recap_eval.normalize import angka_ke_kata, normalize, normalize_text
from recap_eval.vad import FRAME, SR, VadParams, segment_from_probs


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "nol"), (7, "tujuh"), (10, "sepuluh"), (11, "sebelas"), (15, "lima belas"),
        (20, "dua puluh"), (99, "sembilan puluh sembilan"), (100, "seratus"), (115, "seratus lima belas"),
        (1000, "seribu"), (1250, "seribu dua ratus lima puluh"), (2000000, "dua juta"),
        (3500000000, "tiga miliar lima ratus juta"),
    ],
)
def test_angka_ke_kata(n, expected):
    assert angka_ke_kata(n) == expected


def test_normalize_basics():
    assert normalize_text("Halo, Dunia!  Apa kabar?") == "halo dunia apa kabar"
    assert normalize_text("anak-anak bermain") == "anak anak bermain"
    assert normalize_text("Naik 15% jadi Rp1.000.000") == "naik lima belas persen jadi rp satu juta"
    assert normalize_text("nilainya 3,5 poin") == "nilainya tiga koma lima poin"
    assert normalize_text("eh jadi [tidak jelas] begitu ya") == "jadi begitu ya"


def test_spelling_variants_are_not_errors():
    c = score_item("risiko yang memengaruhi apa pun walaupun sering kali", "resiko yang mempengaruhi apapun walau pun seringkali")
    assert c.wer == 0
    assert normalize_text("Mempengaruhi", canonical=False) == "mempengaruhi"


def test_english_mask():
    n = normalize("kita perlu {align} dulu sama {key stakeholder} ya")
    assert n.tokens == ["kita", "perlu", "align", "dulu", "sama", "key", "stakeholder", "ya"]
    assert n.english_mask == [False, False, True, False, False, True, True, False]


def test_score_item_wer_and_cs():
    ref = "kita perlu {align} dulu sama {stakeholder}"
    hyp = "kita perlu alain dulu sama stakeholder"
    c = score_item(ref, hyp)
    assert c.ref_words == 6
    assert c.sub == 1 and c.dele == 0 and c.ins == 0
    assert c.cs_ref_words == 2 and c.cs_errors == 1
    assert c.cs_wer == pytest.approx(0.5)


def test_score_item_ignores_case_punct_numbers():
    c = score_item("Rapat jam 10 tadi, oke?", "rapat jam sepuluh tadi oke")
    assert c.wer == 0


def test_silence_counts_hallucination():
    c = score_item("[hening]", "terima kasih telah menonton", silence_minutes=2.0)
    assert c.ref_words == 0 and c.silence_inserted_words == 4
    assert c.hallucination_wpm == pytest.approx(2.0)


def test_der_perfect_and_confusion():
    ref = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
    assert der(ref, [(0.0, 5.0, "x"), (5.0, 10.0, "y")], collar=0)["der"] == pytest.approx(0, abs=1e-6)
    r = der(ref, [(0.0, 10.0, "x")], collar=0)
    assert r["der"] == pytest.approx(0.5, abs=0.01)  # separuh waktu salah speaker


def _probs(pattern):
    """pattern: list of (seconds, prob)."""
    frames = []
    for secs, p in pattern:
        frames += [p] * int(secs * SR / FRAME)
    return np.array(frames, dtype=np.float32)


def test_segmenter_closes_on_silence():
    probs = _probs([(2, 0.9), (2, 0.05), (3, 0.9)])
    segs = segment_from_probs(probs, len(probs) * FRAME, VadParams(redemption_ms=600, pad_ms=0))
    assert len(segs) == 2
    assert segs[0].start_s == pytest.approx(0, abs=0.05)
    assert segs[0].end_s == pytest.approx(2, abs=0.1)


def test_segmenter_force_cut():
    probs = _probs([(45, 0.9)])
    p = VadParams(max_segment_s=20, pad_ms=0)
    segs = segment_from_probs(probs, len(probs) * FRAME, p)
    assert len(segs) >= 3
    assert all(s.end_s - s.start_s <= 20.05 for s in segs)
    # tidak ada celah: segmen berurutan menyambung
    assert all(abs(a.end - b.start) <= FRAME for a, b in zip(segs, segs[1:]))
