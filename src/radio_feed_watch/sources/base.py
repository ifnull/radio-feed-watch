"""Audio source protocol and shared clip payload."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from radio_feed_watch.config import SourceConfig
from radio_feed_watch.models import SourceType, utcnow


@dataclass
class AudioClip:
    """One speech/call segment ready for storage + STT."""

    source_id: str
    source_type: SourceType
    source_label: str
    audio: bytes
    content_type: str = "audio/mpeg"
    ts: datetime = field(default_factory=utcnow)
    duration_s: float | None = None
    external_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AudioSource(ABC):
    """Yields AudioClip objects from a configured feed."""

    def __init__(self, config: SourceConfig):
        self.config = config

    @property
    def source_id(self) -> str:
        return self.config.id

    @property
    def source_label(self) -> str:
        return self.config.label

    @property
    @abstractmethod
    def source_type(self) -> SourceType: ...

    @abstractmethod
    async def listen(self) -> AsyncIterator[AudioClip]:
        """Async generator of clips. Runs until cancelled."""
        ...

    async def close(self) -> None:
        return None
