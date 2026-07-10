"""RTL-SDR source stub — interface only for v1."""

from __future__ import annotations

from collections.abc import AsyncIterator

from radio_feed_watch.config import SourceConfig
from radio_feed_watch.models import SourceType
from radio_feed_watch.sources.base import AudioClip, AudioSource


class RtlSdrSource(AudioSource):
    """Placeholder so mixed-source config is real; not implemented in v1."""

    @property
    def source_type(self) -> SourceType:
        return SourceType.RTLSDR

    async def listen(self) -> AsyncIterator[AudioClip]:
        raise NotImplementedError(
            f"RTL-SDR source {self.config.id!r} is not implemented yet. "
            "Disable it in the locale pack or wait for a later release."
        )
        yield  # pragma: no cover — makes this an async generator type-wise
