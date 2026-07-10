"""Shared event models for the radio-feed-watch pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    BROADCASTIFY = "broadcastify"
    RTLSDR = "rtlsdr"
    OPENDATA = "opendata"


class IncidentType(str, Enum):
    VEHICLE_ACCIDENT = "vehicle_accident"
    DUI = "dui"
    FIRE = "fire"
    MEDICAL = "medical"
    STRUCTURE_FIRE = "structure_fire"
    WILDFIRE = "wildfire"
    SHOOTING = "shooting"
    ROBBERY = "robbery"
    TRAFFIC_STOP = "traffic_stop"
    HAZMAT = "hazmat"
    RESCUE = "rescue"
    OTHER = "other"
    UNKNOWN = "unknown"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    stem = uuid4().hex[:12]
    return f"{prefix}{stem}" if prefix else stem


class SourceRef(BaseModel):
    source_id: str
    source_type: SourceType
    source_label: str


class TranscriptEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("t_"))
    source_id: str
    source_type: SourceType
    source_label: str
    ts: datetime = Field(default_factory=utcnow)
    text: str
    clip_id: str | None = None
    stt_provider: str | None = None
    confidence: float | None = None
    duration_s: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class IncidentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("i_"))
    source_id: str
    source_type: SourceType
    source_label: str
    ts: datetime = Field(default_factory=utcnow)
    text: str
    incident_type: IncidentType = IncidentType.UNKNOWN
    type_confidence: float = 0.0
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    geo_confidence: float | None = None
    clip_id: str | None = None
    clip_saved: bool = False
    units: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class AlertEvent(IncidentEvent):
    event_id: str = Field(default_factory=lambda: new_id("a_"))
    waypoint_id: str
    waypoint_label: str | None = None
    distance_m: float
    radius_m: float


class ClipRecord(BaseModel):
    clip_id: str
    source_id: str
    source_type: SourceType
    source_label: str
    ts: datetime
    path: str
    duration_s: float | None = None
    saved: bool = False
    text: str | None = None
    external_id: str | None = None
