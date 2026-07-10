"""Deepgram cloud STT provider (optional)."""

from __future__ import annotations

import logging

import httpx

from radio_feed_watch.config import DeepgramSttConfig
from radio_feed_watch.sources.base import AudioClip
from radio_feed_watch.stt.base import Transcriber, TranscriptResult

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class DeepgramTranscriber(Transcriber):
    name = "deepgram"

    def __init__(self, config: DeepgramSttConfig, api_key: str):
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is required when stt.provider: deepgram")
        self.config = config
        self.api_key = api_key

    async def transcribe(self, clip: AudioClip, path=None) -> TranscriptResult:
        params = {
            "model": self.config.model,
            "smart_format": "true",
            "punctuate": "true",
        }
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": clip.content_type or "audio/mpeg",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                DEEPGRAM_URL,
                params=params,
                headers=headers,
                content=clip.audio,
            )
            resp.raise_for_status()
            data = resp.json()

        alt = (
            data.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
        )
        text = (alt.get("transcript") or "").strip()
        confidence = alt.get("confidence")
        return TranscriptResult(
            text=text,
            confidence=float(confidence) if confidence is not None else None,
            provider=self.name,
            raw=data,
        )
