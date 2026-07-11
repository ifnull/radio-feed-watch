"""Config loading tests."""

from pathlib import Path

from radio_feed_watch.config import load_config


def test_load_example_config(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    app = load_config("config.example.yaml")
    assert app.locale.id == "austin"
    assert app.stt.provider == "local"
    enabled = [s for s in app.locale.sources if s.enabled]
    assert enabled
    assert enabled[0].type == "broadcastify"
    assert enabled[0].mode == "stream"
    assert enabled[0].feed_id
    assert app.vad.silence_ms_to_end == 2000
    assert app.dashboard.transcript_burst_gap_s == 3.0
    assert app.filters.min_text_chars == 3
    assert app.filters.dedupe_window_s == 45
    assert app.clips.purge_interval_s == 3600
    assert app.stt.deepgram.model == "nova-2-phonecall"
    assert app.stt.local.model == "small.en"
    assert app.locale.stt_vocab
    assert app.llm_correct.enabled is False
    assert app.llm_correct.max_duration_s == 4.0
