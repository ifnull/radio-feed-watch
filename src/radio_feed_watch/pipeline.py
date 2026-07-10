"""Pipeline: clip → store → STT → classify → geocode → proximity → MQTT/bus."""

from __future__ import annotations

import logging
from pathlib import Path

from radio_feed_watch.bus import EventBus
from radio_feed_watch.classify.rules import classify_incident
from radio_feed_watch.config import AppConfig
from radio_feed_watch.extract.address import extract_addresses
from radio_feed_watch.extract.phonetic import decode_phonetics
from radio_feed_watch.extract.radio_codes import decode_radio_codes
from radio_feed_watch.geo.proximity import Geocoder, nearest_waypoint
from radio_feed_watch.models import AlertEvent, IncidentEvent, TranscriptEvent
from radio_feed_watch.mqtt.publisher import MqttPublisher
from radio_feed_watch.sources.base import AudioClip
from radio_feed_watch.storage.clips import ClipStore
from radio_feed_watch.stt.base import Transcriber

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        app: AppConfig,
        store: ClipStore,
        transcriber: Transcriber,
        mqtt: MqttPublisher | None = None,
        bus: EventBus | None = None,
    ):
        self.app = app
        self.store = store
        self.transcriber = transcriber
        self.mqtt = mqtt
        self.bus = bus
        self.geocoder = Geocoder(app.locale)

    async def handle_clip(self, clip: AudioClip) -> IncidentEvent | None:
        record = None
        if self.app.clips.enabled:
            record = self.store.save_clip(clip)
            logger.info("Saved clip %s (%s bytes)", record.clip_id, len(clip.audio))

        clip_path = Path(record.path) if record is not None else None
        result = await self.transcriber.transcribe(clip, path=clip_path)
        raw_text = result.text.strip()
        if not raw_text:
            logger.info("Empty transcript for %s", clip.source_id)
            return None

        phonetic = decode_phonetics(raw_text)
        text = phonetic.text
        if phonetic.changed:
            logger.info(
                "[%s] phonetic decode: %s",
                clip.source_id,
                ", ".join(f"{h.letters}<={' '.join(h.words)}" for h in phonetic.hits),
            )

        radio = decode_radio_codes(text)
        text = radio.text
        if radio.changed:
            logger.info(
                "[%s] radio codes: %s",
                clip.source_id,
                ", ".join(
                    f"{h.normalized}<={h.raw}" + (f" [{h.meaning}]" if h.meaning else "")
                    for h in radio.hits
                ),
            )

        if record:
            self.store.update_text(record.clip_id, text)

        transcript = TranscriptEvent(
            source_id=clip.source_id,
            source_type=clip.source_type,
            source_label=clip.source_label,
            ts=clip.ts,
            text=text,
            clip_id=record.clip_id if record else None,
            stt_provider=result.provider,
            confidence=result.confidence,
            duration_s=clip.duration_s,
            raw={
                "text_raw": raw_text,
                "phonetic_hits": [
                    {"letters": h.letters, "words": h.words} for h in phonetic.hits
                ],
                "radio_code_hits": [
                    {
                        "raw": h.raw,
                        "normalized": h.normalized,
                        "meaning": h.meaning,
                    }
                    for h in radio.hits
                ],
            },
        )
        logger.info("[%s] %s", clip.source_id, text)
        if self.mqtt:
            await self.mqtt.publish_transcript(transcript)
        if self.bus:
            await self.bus.publish_transcript(transcript)

        itype, type_conf = classify_incident(text, self.app.locale.phrases)
        addresses = extract_addresses(text)
        lat = lon = geo_conf = None
        address = addresses[0] if addresses else None
        if address:
            geo = self.geocoder.geocode(address)
            if geo:
                lat, lon, geo_conf = geo.lat, geo.lon, geo.confidence
                address = geo.address
                logger.info(
                    "[%s] geocoded via %r → %r (%.5f,%.5f)",
                    clip.source_id,
                    geo.query,
                    address,
                    lat,
                    lon,
                )
            else:
                logger.info("[%s] address candidate (ungeocoded): %r", clip.source_id, address)

        incident = IncidentEvent(
            source_id=clip.source_id,
            source_type=clip.source_type,
            source_label=clip.source_label,
            ts=clip.ts,
            text=text,
            incident_type=itype,
            type_confidence=type_conf,
            address=address,
            lat=lat,
            lon=lon,
            geo_confidence=geo_conf,
            clip_id=record.clip_id if record else None,
            clip_saved=bool(record.saved) if record else False,
        )
        if self.mqtt:
            await self.mqtt.publish_incident(incident)
        if self.bus:
            await self.bus.publish_incident(incident)

        if lat is not None and lon is not None and self.app.waypoints:
            hit = nearest_waypoint(lat, lon, self.app.waypoints, itype.value)
            if hit:
                wp, dist = hit
                alert = AlertEvent(
                    **incident.model_dump(),
                    waypoint_id=wp.id,
                    waypoint_label=wp.label,
                    distance_m=dist,
                    radius_m=wp.radius_m,
                )
                logger.warning(
                    "ALERT %s within %.0fm of %s",
                    itype.value,
                    dist,
                    wp.id,
                )
                if self.mqtt:
                    await self.mqtt.publish_alert(alert)
                if self.bus:
                    await self.bus.publish_alert(alert)

        return incident
