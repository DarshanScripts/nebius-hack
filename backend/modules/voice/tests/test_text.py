import pytest

from backend.modules.voice.text import build_srt, build_words, tokenize
from contracts.models import StageFailure, WordTiming


def wt(i, text, s, e):
    return WordTiming(word_id=f"x_w{i:03d}", text=text, start_ms=s, end_ms=e)


def test_tokenize_marks_punctuation_only_tokens():
    toks = tokenize("How does  it work \u2014 really?")
    assert [t.text for t in toks] == ["How", "does", "it", "work", "\u2014", "really?"]
    assert [t.meaningful for t in toks] == [True, True, True, True, False, True]
    assert tokenize("It\u2019s fine")[0].norm == "it's"


def test_build_words_maps_to_script_text_with_contiguous_ids():
    got = [wt(1, "How", 80, 240), wt(2, "does", 250, 390), wt(3, "calling", 410, 790), wt(4, "work", 810, 1100)]
    words = build_words("d001", "How does calling work?", got, 1200)
    assert [w.text for w in words] == ["How", "does", "calling", "work?"]
    assert [w.word_id for w in words] == [f"d001_w00{i}" for i in range(1, 5)]
    assert [(w.start_ms, w.end_ms) for w in words] == [(80, 240), (250, 390), (410, 790), (810, 1100)]


def test_build_words_tolerates_tokenization_differences():
    got = [wt(1, "WhatsApp", 0, 400), wt(2, "s", 400, 450), wt(3, "calls", 450, 900)]
    words = build_words("d002", "WhatsApp's calls", got, 1000)
    assert [(w.text, w.start_ms, w.end_ms) for w in words] == [("WhatsApp's", 0, 450), ("calls", 450, 900)]


def test_build_words_omitted_word_is_incomplete():
    got = [wt(1, "How", 0, 100), wt(2, "work", 200, 300)]
    with pytest.raises(StageFailure) as exc:
        build_words("d001", "How does it work", got, 1000)
    err = exc.value.error
    assert err.code == "ALIGNMENT_INCOMPLETE" and err.retryable


def test_build_words_different_transcript_is_rejected():
    got = [wt(1, "Completely", 0, 100), wt(2, "different", 100, 300), wt(3, "words", 300, 500)]
    with pytest.raises(StageFailure) as exc:
        build_words("d001", "How does calling work", got, 1000)
    assert exc.value.error.code == "ALIGNMENT_INCOMPLETE"


def test_build_words_enforces_order_positive_length_and_clip_bounds():
    got = [wt(1, "a", 100, 300), wt(2, "b", 250, 250), wt(3, "c", 900, 1500)]
    words = build_words("d001", "a b c", got, 1000)
    assert [(w.start_ms, w.end_ms) for w in words] == [(100, 300), (300, 301), (900, 1000)]
    out = [wt(1, "a", 1000, 1200)]
    with pytest.raises(StageFailure) as exc:
        build_words("d001", "a", out, 1000)
    assert exc.value.error.code == "ALIGNMENT_INVALID"


def test_srt_format_and_sentence_breaks():
    words = [wt(1, "Hello", 0, 400), wt(2, "there.", 400, 900), wt(3, "Next", 1000, 1500)]
    srt = build_srt(words)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:00,900\nHello there.\n")
    assert "2\n00:00:01,000 --> 00:00:01,500\nNext" in srt
