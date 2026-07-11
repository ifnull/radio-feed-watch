"""Local faster-whisper STT provider — tuned for short radio bursts."""

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

    def __init__(self, config: LocalSttConfig, locale_vocab: list[str] | None = None):
        self.config = config
        self.locale_vocab = [v.strip() for v in (locale_vocab or []) if v and v.strip()]
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

    def _prompt(self) -> str | None:
        parts = [self.config.initial_prompt.strip()] if self.config.initial_prompt else []
        if self.locale_vocab:
            parts.append("Local terms: " + ", ".join(self.locale_vocab[:40]) + ".")
        prompt = " ".join(p for p in parts if p).strip()
        # Whisper prompt is most effective when kept relatively short
        return prompt[:800] if prompt else None

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
                vad_filter=self.config.vad_filter,
                initial_prompt=self._prompt(),
                condition_on_previous_text=self.config.condition_on_previous_text,
                temperature=self.config.temperature,
                no_speech_threshold=self.config.no_speech_threshold,
            )
            parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
            text = " ".join(parts).strip()
            # Average segment avg_logprob as a rough confidence proxy when available
            conf = None
            probs = [
                float(seg.avg_logprob)
                for seg in segments
                if getattr(seg, "avg_logprob", None) is not None
            ]
            if probs:
                # map typical logprob [-1, 0] → [0, 1] (clamped)
                avg = sum(probs) / len(probs)
                conf = max(0.0, min(1.0, 1.0 + avg))
            return TranscriptResult(
                text=text,
                confidence=conf,
                provider=self.name,
                language=getattr(info, "language", "en"),
            )
        finally:
            if tmp is not None:
                Path(tmp.name).unlink(missing_ok=True)
