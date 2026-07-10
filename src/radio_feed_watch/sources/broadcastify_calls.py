"""Broadcastify Calls API source (optional / advanced).

Prefer the live listen stream (`broadcastify_stream`) for most users — it only
needs username/password Basic auth and no developer API approval.

This module remains for accounts that already have Calls API credentials and
want per-call MP3s without VAD chunking.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

import httpx

from radio_feed_watch.config import EnvSettings, SourceConfig
from radio_feed_watch.models import SourceType
from radio_feed_watch.sources.base import AudioClip, AudioSource

logger = logging.getLogger(__name__)

AUTH_URL = "https://api.bcfy.io/common/v1/auth"
LIVE_URL = "https://api.bcfy.io/calls/v1/live/"
POLL_INTERVAL_S = 5.0


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_broadcastify_jwt(
    api_key_id: str,
    api_key_secret: str,
    app_id: str,
    uid: str | None = None,
    user_token: str | None = None,
    ttl_s: int = 3600,
) -> str:
    """HS256 JWT for Broadcastify Calls API (kid = API key id)."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": api_key_id}
    payload: dict[str, Any] = {"iss": app_id, "iat": now, "exp": now + ttl_s}
    if uid and user_token:
        payload["sub"] = int(uid)
        payload["utk"] = user_token

    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(api_key_secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


class BroadcastifyAuth:
    def __init__(self, env: EnvSettings):
        self.env = env
        self._uid: str | None = None
        self._token: str | None = None
        self._exp: float = 0

    def _require(self) -> None:
        missing = [
            name
            for name, val in [
                ("BROADCASTIFY_API_KEY_ID", self.env.broadcastify_api_key_id),
                ("BROADCASTIFY_API_KEY_SECRET", self.env.broadcastify_api_key_secret),
                ("BROADCASTIFY_APP_ID", self.env.broadcastify_app_id),
                ("BROADCASTIFY_USERNAME", self.env.broadcastify_username),
                ("BROADCASTIFY_PASSWORD", self.env.broadcastify_password),
            ]
            if not val
        ]
        if missing:
            raise RuntimeError(
                "Broadcastify credentials missing: " + ", ".join(missing) + ". See .env.example."
            )

    async def ensure(self, client: httpx.AsyncClient) -> tuple[str, str]:
        self._require()
        if self._uid and self._token and self._exp > time.time() + 60:
            return self._uid, self._token

        app_jwt = generate_broadcastify_jwt(
            self.env.broadcastify_api_key_id,
            self.env.broadcastify_api_key_secret,
            self.env.broadcastify_app_id,
        )
        body = urlencode(
            {
                "username": self.env.broadcastify_username,
                "password": self.env.broadcastify_password,
            }
        )
        resp = await client.post(
            AUTH_URL,
            content=body,
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "radio-feed-watch/0.1",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._uid = str(data["uid"])
        self._token = str(data["token"])
        self._exp = float(data.get("exp") or (time.time() + 3500))
        logger.info("Broadcastify auth ok (uid=%s)", self._uid)
        return self._uid, self._token

    async def user_jwt(self, client: httpx.AsyncClient) -> str:
        uid, token = await self.ensure(client)
        return generate_broadcastify_jwt(
            self.env.broadcastify_api_key_id,
            self.env.broadcastify_api_key_secret,
            self.env.broadcastify_app_id,
            uid=uid,
            user_token=token,
        )


class BroadcastifySource(AudioSource):
    """Poll Broadcastify live calls for a group and download MP3s."""

    def __init__(self, config: SourceConfig, env: EnvSettings, auth: BroadcastifyAuth | None = None):
        super().__init__(config)
        if not config.group_id:
            raise ValueError(f"broadcastify source {config.id} requires group_id")
        self.env = env
        self.auth = auth or BroadcastifyAuth(env)
        self._last_pos: int = 0
        self._seen: set[str] = set()

    @property
    def source_type(self) -> SourceType:
        return SourceType.BROADCASTIFY

    async def listen(self) -> AsyncIterator[AudioClip]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    async for clip in self._poll_once(client):
                        yield clip
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Broadcastify poll failed for %s", self.source_id)
                await asyncio.sleep(POLL_INTERVAL_S)

    async def _poll_once(self, client: httpx.AsyncClient) -> AsyncIterator[AudioClip]:
        jwt = await self.auth.user_jwt(client)
        params: dict[str, str] = {"groups": self.config.group_id or ""}
        if self._last_pos:
            params["pos"] = str(self._last_pos)
        else:
            params["init"] = "1"

        resp = await client.get(
            LIVE_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {jwt}",
                "User-Agent": "radio-feed-watch/0.1",
            },
        )
        if resp.status_code == 429:
            logger.warning("Broadcastify rate limited; backing off")
            await asyncio.sleep(10)
            return
        resp.raise_for_status()
        data = resp.json()
        if data.get("lastPos") is not None:
            self._last_pos = int(data["lastPos"])

        calls = data.get("calls") or []
        for call in calls:
            clip = await self._call_to_clip(client, call)
            if clip:
                yield clip

    async def _call_to_clip(self, client: httpx.AsyncClient, call: dict[str, Any]) -> AudioClip | None:
        group_id = str(call.get("groupId") or self.config.group_id or "")
        ts = call.get("ts")
        start_ts = call.get("start_ts") or ts
        external_id = f"{group_id}-{ts}-{start_ts}"
        if external_id in self._seen:
            return None
        self._seen.add(external_id)
        if len(self._seen) > 5000:
            self._seen = set(list(self._seen)[-2500:])

        url = call.get("url")
        if not url:
            logger.debug("Call missing audio url: %s", external_id)
            return None

        # Calls API returns a direct audio URL; no auth header required for the file itself.
        audio_resp = await client.get(str(url), headers={"User-Agent": "radio-feed-watch/0.1"})
        audio_resp.raise_for_status()
        try:
            duration_s = float(call["duration"]) if call.get("duration") is not None else None
        except (TypeError, ValueError):
            duration_s = None

        meta = {k: call[k] for k in ("groupId", "ts", "start_ts", "descr", "duration") if k in call}
        return AudioClip(
            source_id=self.source_id,
            source_type=self.source_type,
            source_label=self.source_label,
            audio=audio_resp.content,
            content_type=audio_resp.headers.get("content-type", "audio/mpeg"),
            duration_s=duration_s,
            external_id=external_id,
            metadata=meta,
        )
