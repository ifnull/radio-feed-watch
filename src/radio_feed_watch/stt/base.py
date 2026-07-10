"""STT provider protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from radio_feed_watch.sources.base import AudioClip


@dataclass
class TranscriptResult:
    text: str
    confidence: float | None = None
    provider: str = "unknown"
    language: str | None = None
    raw: dict | None = None


class Transcriber(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, clip: AudioClip, path: Path | None = None) -> TranscriptResult:
        """Transcribe clip bytes (and optional on-disk path)."""
        ...
