from radio_feed_watch.config import FilterConfig
from radio_feed_watch.filters import (
    TranscriptDeduper,
    evaluate_transcript,
    normalize_text,
    remap_short_ack,
    should_skip_clip,
)


def test_normalize_collapses_punct():
    assert normalize_text("Ten-Four!!") == "ten four"
    assert normalize_text("  Hello,   world. ") == "hello world"


def test_skip_short_clip():
    f = FilterConfig(min_clip_duration_s=0.5)
    assert not should_skip_clip(duration_s=0.2, filters=f).ok
    assert should_skip_clip(duration_s=1.0, filters=f).ok


def test_drop_empty_and_short():
    f = FilterConfig(min_text_chars=3, min_confidence=None)
    d = TranscriptDeduper(45, 0.92)
    assert not evaluate_transcript(
        text="  ", confidence=None, filters=f, source_id="a", deduper=d
    ).ok
    assert not evaluate_transcript(
        text="ok", confidence=None, filters=f, source_id="a", deduper=d
    ).ok
    assert evaluate_transcript(
        text="688", confidence=None, filters=f, source_id="a", deduper=d
    ).ok


def test_drop_noise_phrase():
    f = FilterConfig(min_confidence=None)
    d = TranscriptDeduper(45, 0.92)
    gate = evaluate_transcript(
        text="Thanks for watching!",
        confidence=0.9,
        filters=f,
        source_id="a",
        deduper=d,
    )
    assert not gate.ok
    assert gate.reason and gate.reason.startswith("noise_phrase")


def test_drop_low_confidence():
    f = FilterConfig(min_confidence=0.4, min_text_chars=1)
    d = TranscriptDeduper(45, 0.92)
    assert not evaluate_transcript(
        text="Engine 5 responding",
        confidence=0.2,
        filters=f,
        source_id="a",
        deduper=d,
    ).ok
    assert evaluate_transcript(
        text="Engine 5 responding",
        confidence=0.5,
        filters=f,
        source_id="a",
        deduper=d,
    ).ok


def test_dedupe_exact_and_near():
    f = FilterConfig(min_confidence=None, dedupe_window_s=60, dedupe_similarity=0.9)
    d = TranscriptDeduper(f.dedupe_window_s, f.dedupe_similarity)
    t1 = "Units at Congress and 6th for an MVC"
    assert evaluate_transcript(
        text=t1, confidence=None, filters=f, source_id="austin", deduper=d
    ).ok
    d.remember("austin", t1)

    # exact (punct/case differ)
    gate = evaluate_transcript(
        text="units at congress and 6th for an mvc!",
        confidence=None,
        filters=f,
        source_id="austin",
        deduper=d,
    )
    assert not gate.ok
    assert gate.reason == "duplicate"

    # near-duplicate
    gate2 = evaluate_transcript(
        text="Units at Congress and 6th for MVC",
        confidence=None,
        filters=f,
        source_id="austin",
        deduper=d,
    )
    assert not gate2.ok

    # different source is fine
    assert evaluate_transcript(
        text=t1, confidence=None, filters=f, source_id="other", deduper=d
    ).ok


def test_short_ack_remap_never():
    from radio_feed_watch.extract.radio_codes import decode_radio_codes

    f = FilterConfig(short_ack_remap=True, short_ack_max_duration_s=3.0)
    ack = remap_short_ack(text="Never.", duration_s=2.4, filters=f)
    assert ack.changed
    assert ack.to_text == "ten four"
    radio = decode_radio_codes(ack.text)
    assert "10-4" in radio.text


def test_short_ack_remap_skips_long_clip_and_sentence():
    f = FilterConfig()
    assert not remap_short_ack(text="Never.", duration_s=8.0, filters=f).changed
    assert not remap_short_ack(
        text="I will never go there", duration_s=2.0, filters=f
    ).changed


def test_short_ack_remap_shower_tower():
    f = FilterConfig()
    assert remap_short_ack(text="Shower.", duration_s=1.5, filters=f).to_text == "ten four"
    assert remap_short_ack(text="Tower", duration_s=1.2, filters=f).to_text == "ten four"
