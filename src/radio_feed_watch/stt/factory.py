"""STT factory."""

from __future__ import annotations

from radio_feed_watch.config import AppConfig
from radio_feed_watch.stt.base import Transcriber
from radio_feed_watch.stt.deepgram import DeepgramTranscriber
from radio_feed_watch.stt.local_whisper import LocalWhisperTranscriber


def build_transcriber(app: AppConfig) -> Transcriber:
    if app.stt.provider == "deepgram":
        return DeepgramTranscriber(app.stt.deepgram, app.env.deepgram_api_key)
    return LocalWhisperTranscriber(app.stt.local)
