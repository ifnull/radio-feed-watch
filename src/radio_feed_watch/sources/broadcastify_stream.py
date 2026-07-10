"""Broadcastify live listen stream (default) — Basic auth, no developer API approval."""

from __future__ import annotations

import asyncio
import audioop
import base64
import logging
import wave
from collections.abc import AsyncIterator
from io import BytesIO

import httpx

from radio_feed_watch.config import EnvSettings, SourceConfig, VadConfig
from radio_feed_watch.models import SourceType
from radio_feed_watch.sources.base import AudioClip, AudioSource

logger = logging.getLogger(__name__)

STREAM_URL = "https://audio.broadcastify.com/{feed_id}.mp3"
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # 16-bit
CHANNELS = 1
FRAME_MS = 30
FRAME_BYTES = int(SAMPLE_RATE * FRAME_MS / 1000) * SAMPLE_WIDTH * CHANNELS


def basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class BroadcastifyStreamSource(AudioSource):
    """
    Continuous MP3 listen feed with Basic auth.

    URL: https://audio.broadcastify.com/{feed_id}.mp3
    Needs BROADCASTIFY_USERNAME / BROADCASTIFY_PASSWORD only (no API keys).
    Requires ffmpeg on PATH to decode MP3 → PCM for VAD chunking.
    """

    def __init__(
        self,
        config: SourceConfig,
        env: EnvSettings,
        vad: VadConfig | None = None,
    ):
        super().__init__(config)
        if not config.feed_id:
            raise ValueError(f"broadcastify stream source {config.id} requires feed_id")
        self.env = env
        self.feed_id = str(config.feed_id)
        # Per-source override wins over app-level defaults
        self.vad = config.vad or vad or VadConfig()

    @property
    def source_type(self) -> SourceType:
        return SourceType.BROADCASTIFY

    def _require_user(self) -> tuple[str, str]:
        user = self.env.broadcastify_username
        password = self.env.broadcastify_password
        if not user or not password:
            raise RuntimeError(
                "BROADCASTIFY_USERNAME and BROADCASTIFY_PASSWORD are required "
                "for live stream ingest. See .env.example."
            )
        return user, password

    async def listen(self) -> AsyncIterator[AudioClip]:
        user, password = self._require_user()
        url = STREAM_URL.format(feed_id=self.feed_id)
        headers = {
            "Authorization": basic_auth_header(user, password),
            "User-Agent": "radio-feed-watch/0.1",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        }
        logger.info(
            "Stream VAD %s: silence_ms=%d min_speech_ms=%d speech_rms=%d",
            self.source_id,
            self.vad.silence_ms_to_end,
            self.vad.min_speech_ms,
            self.vad.speech_rms,
        )

        while True:
            try:
                async for clip in self._session(url, headers):
                    yield clip
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Broadcastify stream error for %s; reconnecting in 5s", self.source_id
                )
                await asyncio.sleep(5)

    async def _session(self, url: str, headers: dict[str, str]) -> AsyncIterator[AudioClip]:
        logger.info("Connecting stream %s → %s", self.source_id, url)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code in (401, 403):
                    raise RuntimeError(
                        f"Broadcastify stream auth failed ({resp.status_code}). "
                        "Check username/password and feed access."
                    )
                resp.raise_for_status()

                try:
                    ffmpeg = await asyncio.create_subprocess_exec(
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        "pipe:0",
                        "-f",
                        "s16le",
                        "-ac",
                        "1",
                        "-ar",
                        str(SAMPLE_RATE),
                        "pipe:1",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                except FileNotFoundError as exc:
                    raise RuntimeError(
                        "ffmpeg is required for Broadcastify stream ingest. "
                        "Install ffmpeg and ensure it is on PATH."
                    ) from exc

                assert ffmpeg.stdin and ffmpeg.stdout

                async def _pump_mp3() -> None:
                    assert ffmpeg.stdin is not None
                    try:
                        async for chunk in resp.aiter_bytes(chunk_size=4096):
                            ffmpeg.stdin.write(chunk)
                            await ffmpeg.stdin.drain()
                    except Exception:
                        logger.debug("MP3 pump ended for %s", self.source_id)
                    finally:
                        try:
                            ffmpeg.stdin.close()
                        except Exception:
                            pass

                pump = asyncio.create_task(_pump_mp3())
                try:
                    async for clip in self._vad_clips(ffmpeg.stdout):
                        yield clip
                finally:
                    pump.cancel()
                    try:
                        ffmpeg.kill()
                    except ProcessLookupError:
                        pass
                    await ffmpeg.wait()

    async def _vad_clips(self, pcm_stream: asyncio.StreamReader) -> AsyncIterator[AudioClip]:
        pending = bytearray()
        speech = bytearray()
        in_speech = False
        silence_ms = 0
        speech_ms = 0
        speech_rms = self.vad.speech_rms
        silence_ms_to_end = self.vad.silence_ms_to_end
        min_speech_ms = self.vad.min_speech_ms
        max_speech_ms = self.vad.max_speech_ms

        while True:
            chunk = await pcm_stream.read(FRAME_BYTES)
            if not chunk:
                if in_speech and speech_ms >= min_speech_ms:
                    yield self._make_clip(bytes(speech), speech_ms / 1000.0)
                break

            pending.extend(chunk)
            while len(pending) >= FRAME_BYTES:
                frame = bytes(pending[:FRAME_BYTES])
                del pending[:FRAME_BYTES]
                rms = audioop.rms(frame, SAMPLE_WIDTH)

                if rms >= speech_rms:
                    if not in_speech:
                        in_speech = True
                        speech = bytearray()
                        speech_ms = 0
                        silence_ms = 0
                    speech.extend(frame)
                    speech_ms += FRAME_MS
                    silence_ms = 0
                    if speech_ms >= max_speech_ms:
                        yield self._make_clip(bytes(speech), speech_ms / 1000.0)
                        in_speech = False
                        speech = bytearray()
                        speech_ms = 0
                elif in_speech:
                    speech.extend(frame)
                    speech_ms += FRAME_MS
                    silence_ms += FRAME_MS
                    if silence_ms >= silence_ms_to_end and speech_ms >= min_speech_ms:
                        keep_ms = max(min_speech_ms, speech_ms - silence_ms + 200)
                        keep_bytes = int(SAMPLE_RATE * keep_ms / 1000) * SAMPLE_WIDTH
                        payload = bytes(speech[:keep_bytes]) if keep_bytes < len(speech) else bytes(speech)
                        yield self._make_clip(payload, keep_ms / 1000.0)
                        in_speech = False
                        speech = bytearray()
                        speech_ms = 0
                        silence_ms = 0

    def _make_clip(self, pcm: bytes, duration_s: float) -> AudioClip:
        return AudioClip(
            source_id=self.source_id,
            source_type=self.source_type,
            source_label=self.source_label,
            audio=pcm_to_wav(pcm),
            content_type="audio/wav",
            duration_s=duration_s,
            external_id=None,
            metadata={"feed_id": self.feed_id, "ingest": "stream"},
        )
