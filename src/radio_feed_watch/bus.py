"""In-memory event bus for live dashboard (ring buffers + SSE subscribers)."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from radio_feed_watch.models import AlertEvent, IncidentEvent, TranscriptEvent


class EventBus:
    def __init__(self, maxlen: int = 200):
        self.transcripts: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.incidents: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.alerts: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._subs: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = asyncio.Lock()

    async def publish(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"kind": kind, **payload}
        async with self._lock:
            if kind == "transcript":
                self.transcripts.appendleft(payload)
            elif kind == "incident":
                self.incidents.appendleft(payload)
            elif kind == "alert":
                self.alerts.appendleft(payload)
            dead: list[asyncio.Queue[dict[str, Any]]] = []
            for q in self._subs:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subs.remove(q)

    async def publish_transcript(self, event: TranscriptEvent) -> None:
        await self.publish("transcript", event.model_dump(mode="json"))

    async def publish_incident(self, event: IncidentEvent) -> None:
        await self.publish("incident", event.model_dump(mode="json"))

    async def publish_alert(self, event: AlertEvent) -> None:
        await self.publish("alert", event.model_dump(mode="json"))

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def snapshot(self) -> dict[str, Any]:
        return {
            "transcripts": list(self.transcripts),
            "incidents": list(self.incidents),
            "alerts": list(self.alerts),
        }
