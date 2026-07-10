"""Configuration loading for radio-feed-watch."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def _expand_env(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        key, default = match.group(1), match.group(2)
        return os.environ.get(key, default if default is not None else "")

    return _ENV_PATTERN.sub(repl, value)


def _expand_tree(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _expand_tree(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_tree(v) for v in node]
    if isinstance(node, str):
        return _expand_env(node)
    return node


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    broadcastify_api_key_id: str = ""
    broadcastify_api_key_secret: str = ""
    broadcastify_app_id: str = ""
    broadcastify_username: str = ""
    broadcastify_password: str = ""
    deepgram_api_key: str = ""
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_topic_prefix: str = "radio"


class LocalSttConfig(BaseModel):
    model: str = "base.en"
    compute_type: str = "int8"
    device: str = "cpu"
    beam_size: int = 1


class DeepgramSttConfig(BaseModel):
    model: str = "nova-2"


class SttConfig(BaseModel):
    provider: Literal["local", "deepgram"] = "local"
    local: LocalSttConfig = Field(default_factory=LocalSttConfig)
    deepgram: DeepgramSttConfig = Field(default_factory=DeepgramSttConfig)


class ClipsConfig(BaseModel):
    enabled: bool = True
    dir: str = "./data/clips"
    format: Literal["opus", "wav"] = "opus"
    retention_days: int = 7
    max_total_gb: float = 10.0


class VadConfig(BaseModel):
    """Energy VAD for live stream chunking (Broadcastify MP3 → clips)."""

    speech_rms: int = 500
    # Longer gap keeps unit ID + follow-up in one clip (PTT often has ~1s quiet).
    silence_ms_to_end: int = 2000
    min_speech_ms: int = 600
    max_speech_ms: int = 45_000


class MqttConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 1883
    username: str = ""
    password: str = ""
    topic_prefix: str = "radio"


class DashboardConfig(BaseModel):
    mode: Literal["ops", "demo"] = "ops"
    host: str = "0.0.0.0"
    port: int = 8080
    brand_name: str = "radio-feed-watch"
    # Group same-source transcript rows within this gap into one burst block.
    transcript_burst_gap_s: float = 3.0


class WaypointConfig(BaseModel):
    id: str
    label: str | None = None
    lat: float
    lon: float
    radius_m: float = 800
    incident_types: list[str] = Field(default_factory=list)


class BBoxConfig(BaseModel):
    south: float
    west: float
    north: float
    east: float


class GeocodeLocaleConfig(BaseModel):
    country_codes: str = "us"
    viewbox: str | None = None
    default_city: str | None = None
    default_state: str | None = None
    default_county: str | None = None
    # Optional postal codes to bias rural / unincorporated addresses (e.g. 78734)
    postal_codes: list[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    id: str
    type: Literal["broadcastify", "rtlsdr", "opendata"]
    enabled: bool = True
    label: str
    # broadcastify: "stream" (default, Basic auth listen URL) | "calls" (developer API)
    mode: Literal["stream", "calls"] = "stream"
    feed_id: str | None = None  # stream: https://audio.broadcastify.com/{feed_id}.mp3
    group_id: str | None = None  # calls: Broadcastify Calls API group id
    device_index: int | None = None
    frequencies: list[float] = Field(default_factory=list)
    # Optional per-source VAD override (stream mode only)
    vad: VadConfig | None = None


class LocaleDashboardConfig(BaseModel):
    map_center: dict[str, float] = Field(default_factory=dict)
    demo_title: str | None = None
    demo_blurb: str | None = None


class LocaleConfig(BaseModel):
    id: str
    label: str
    timezone: str = "UTC"
    bbox: BBoxConfig | None = None
    geocode: GeocodeLocaleConfig = Field(default_factory=GeocodeLocaleConfig)
    sources: list[SourceConfig] = Field(default_factory=list)
    phrases: dict[str, list[str]] = Field(default_factory=dict)
    dashboard: LocaleDashboardConfig = Field(default_factory=LocaleDashboardConfig)


class AppConfig(BaseModel):
    locale_path: str
    locale: LocaleConfig
    stt: SttConfig = Field(default_factory=SttConfig)
    clips: ClipsConfig = Field(default_factory=ClipsConfig)
    vad: VadConfig = Field(default_factory=VadConfig)
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    waypoints: list[WaypointConfig] = Field(default_factory=list)
    env: EnvSettings = Field(default_factory=EnvSettings)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return _expand_tree(data)


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        example = Path("config.example.yaml")
        if example.exists():
            path = example
        else:
            raise FileNotFoundError(f"Missing config: {config_path}")

    raw = _load_yaml(path)
    locale_rel = raw.get("locale")
    if not locale_rel:
        raise ValueError("config must set `locale:` to a locale pack path")

    locale_path = Path(locale_rel)
    if not locale_path.is_absolute():
        locale_path = Path.cwd() / locale_path
    locale_raw = _load_yaml(locale_path)

    env = EnvSettings()
    mqtt_raw = raw.get("mqtt") or {}
    mqtt = MqttConfig(
        enabled=bool(mqtt_raw.get("enabled", False)),
        host=str(mqtt_raw.get("host") or env.mqtt_host),
        port=int(mqtt_raw.get("port") or env.mqtt_port),
        username=str(mqtt_raw.get("username") or env.mqtt_username),
        password=str(mqtt_raw.get("password") or env.mqtt_password),
        topic_prefix=str(mqtt_raw.get("topic_prefix") or env.mqtt_topic_prefix),
    )

    return AppConfig(
        locale_path=str(locale_path),
        locale=LocaleConfig.model_validate(locale_raw),
        stt=SttConfig.model_validate(raw.get("stt") or {}),
        clips=ClipsConfig.model_validate(raw.get("clips") or {}),
        vad=VadConfig.model_validate(raw.get("vad") or {}),
        mqtt=mqtt,
        dashboard=DashboardConfig.model_validate(raw.get("dashboard") or {}),
        waypoints=[WaypointConfig.model_validate(w) for w in (raw.get("waypoints") or [])],
        env=env,
    )
