"""Source manager — start/stop N audio sources."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from radio_feed_watch.config import AppConfig, SourceConfig
from radio_feed_watch.sources.base import AudioClip, AudioSource
from radio_feed_watch.sources.broadcastify_calls import BroadcastifyAuth, BroadcastifySource
from radio_feed_watch.sources.broadcastify_stream import BroadcastifyStreamSource
from radio_feed_watch.sources.rtlsdr import RtlSdrSource

logger = logging.getLogger(__name__)

ClipHandler = Callable[[AudioClip], Awaitable[None]]


def build_source(config: SourceConfig, app: AppConfig, auth: BroadcastifyAuth | None) -> AudioSource:
    if config.type == "broadcastify":
        if config.mode == "calls":
            return BroadcastifySource(config, app.env, auth=auth)
        return BroadcastifyStreamSource(config, app.env, vad=app.vad)
    if config.type == "rtlsdr":
        return RtlSdrSource(config)
    raise ValueError(f"Unsupported source type: {config.type}")


class SourceManager:
    def __init__(self, app: AppConfig):
        self.app = app
        self._auth = BroadcastifyAuth(app.env)
        self._tasks: list[asyncio.Task[None]] = []
        self._sources: list[AudioSource] = []

    def enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.app.locale.sources if s.enabled]

    async def run(self, on_clip: ClipHandler) -> None:
        enabled = self.enabled_sources()
        if not enabled:
            raise RuntimeError("No enabled sources in locale pack")

        for cfg in enabled:
            if cfg.type == "rtlsdr":
                logger.warning("Skipping RTL-SDR stub source %s (not implemented)", cfg.id)
                continue
            source = build_source(cfg, self.app, self._auth)
            self._sources.append(source)
            self._tasks.append(asyncio.create_task(self._pump(source, on_clip), name=f"src:{cfg.id}"))

        if not self._tasks:
            raise RuntimeError("No runnable sources after filtering stubs")

        logger.info("Running %d source worker(s)", len(self._tasks))
        try:
            await asyncio.gather(*self._tasks)
        finally:
            await self.close()

    async def _pump(self, source: AudioSource, on_clip: ClipHandler) -> None:
        logger.info("Source started: %s (%s)", source.source_id, source.source_type.value)
        try:
            async for clip in source.listen():
                await on_clip(clip)
        except asyncio.CancelledError:
            raise
        except NotImplementedError as exc:
            logger.error("%s", exc)
        except Exception:
            logger.exception("Source crashed: %s", source.source_id)
        finally:
            await source.close()
            logger.info("Source stopped: %s", source.source_id)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for source in self._sources:
            await source.close()
        self._sources.clear()
