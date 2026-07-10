"""Local faster-whisper STT provider."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from radio_feed_watch.config import LocalSttConfig
from radio_feed_watch.sources.base import AudioClip
from radio_feed_watch.stt.base import Transcriber, TranscriptResult

logger = logging.getLogger(__name__)


class LocalWhisperTranscriber(Transcriber):
    name = "local"

    def __init__(self, config: LocalSttConfig):
        self.config = config
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. "
                "pip install 'radio-feed-watch[local-stt]' or set stt.provider: deepgram"
            ) from exc
        logger.info(
            "Loading faster-whisper model=%s device=%s compute=%s",
            self.config.model,
            self.config.device,
            self.config.compute_type,
        )
        self._model = WhisperModel(
            self.config.model,
            device=self.config.device,
            compute_type=self.config.compute_type,
        )
        return self._model

    async def transcribe(self, clip: AudioClip, path: Path | None = None) -> TranscriptResult:
        return await asyncio.to_thread(self._transcribe_sync, clip, path)

    def _transcribe_sync(self, clip: AudioClip, path: Path | None) -> TranscriptResult:
        model = self._load()
        audio_path = path
        tmp: tempfile.NamedTemporaryFile | None = None
        if audio_path is None:
            suffix = ".mp3" if "mpeg" in clip.content_type or "mp3" in clip.content_type else ".wav"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(clip.audio)
            tmp.close()
            audio_path = Path(tmp.name)
        try:
            segments, info = model.transcribe(
                str(audio_path),
                language="en",
                beam_size=self.config.beam_size,
                vad_filter=True,
            )
            parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
            text = " ".join(parts).strip()
            return TranscriptResult(
                text=text,
                confidence=None,
                provider=self.name,
                language=getattr(info, "language", "en"),
            )
        finally:
            if tmp is not None:
                Path(tmp.name).unlink(missing_ok=True)
