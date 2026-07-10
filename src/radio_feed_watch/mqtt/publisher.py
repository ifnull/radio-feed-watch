"""MQTT publisher for Home Assistant (optional)."""

from __future__ import annotations

import json
import logging
from typing import Any

from radio_feed_watch.config import MqttConfig
from radio_feed_watch.models import AlertEvent, IncidentEvent, TranscriptEvent

logger = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(self, config: MqttConfig):
        self.config = config
        self._client = None

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    async def connect(self) -> None:
        if not self.config.enabled:
            return
        try:
            from aiomqtt import Client
        except ImportError as exc:
            raise RuntimeError("aiomqtt is required for MQTT publishing") from exc
        self._client = Client(
            hostname=self.config.host,
            port=self.config.port,
            username=self.config.username or None,
            password=self.config.password or None,
        )
        await self._client.__aenter__()
        logger.info("MQTT connected to %s:%s", self.config.host, self.config.port)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    def _topic(self, source_id: str, kind: str) -> str:
        return f"{self.config.topic_prefix}/{source_id}/{kind}"

    async def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if not self.config.enabled or self._client is None:
            return
        await self._client.publish(topic, json.dumps(payload, default=str))

    async def publish_transcript(self, event: TranscriptEvent) -> None:
        await self._publish(self._topic(event.source_id, "transcript"), event.model_dump(mode="json"))

    async def publish_incident(self, event: IncidentEvent) -> None:
        await self._publish(self._topic(event.source_id, "incident"), event.model_dump(mode="json"))

    async def publish_alert(self, event: AlertEvent) -> None:
        await self._publish(self._topic(event.source_id, "alert"), event.model_dump(mode="json"))
