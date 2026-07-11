"""Deepgram cloud STT provider (optional) — radio/phone-oriented defaults."""

from __future__ import annotations

import logging

import httpx

from radio_feed_watch.config import DeepgramSttConfig
from radio_feed_watch.sources.base import AudioClip
from radio_feed_watch.stt.base import Transcriber, TranscriptResult

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


def _uses_keyterm(model: str) -> bool:
    m = model.lower()
    return m.startswith("nova-3") or m.startswith("flux")


class DeepgramTranscriber(Transcriber):
    name = "deepgram"

    def __init__(
        self,
        config: DeepgramSttConfig,
        api_key: str,
        locale_vocab: list[str] | None = None,
    ):
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is required when stt.provider: deepgram")
        self.config = config
        self.api_key = api_key
        self.locale_vocab = [v.strip() for v in (locale_vocab or []) if v and v.strip()]

    def _vocab(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for term in [*self.config.keywords, *self.locale_vocab]:
            t = term.strip()
            if not t:
                continue
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
        return out[:80]  # stay well under API limits

    def _build_params(self) -> list[tuple[str, str]]:
        cfg = self.config
        params: list[tuple[str, str]] = [
            ("model", cfg.model),
            ("language", cfg.language),
            ("smart_format", "true" if cfg.smart_format else "false"),
            ("punctuate", "true" if cfg.punctuate else "false"),
            ("numerals", "true" if cfg.numerals else "false"),
        ]
        vocab = self._vocab()
        if not vocab:
            return params

        if _uses_keyterm(cfg.model):
            for term in vocab:
                params.append(("keyterm", term))
        else:
            intensifier = cfg.keyword_intensifier
            for term in vocab:
                # keywords=word:1.5 — boost uncommon radio terms
                params.append(("keywords", f"{term}:{intensifier:g}"))
        return params

    async def transcribe(self, clip: AudioClip, path=None) -> TranscriptResult:
        params = self._build_params()
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": clip.content_type or "audio/mpeg",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                DEEPGRAM_URL,
                params=params,
                headers=headers,
                content=clip.audio,
            )
            resp.raise_for_status()
            data = resp.json()

        alt = (
            data.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
        )
        text = (alt.get("transcript") or "").strip()
        confidence = alt.get("confidence")
        return TranscriptResult(
            text=text,
            confidence=float(confidence) if confidence is not None else None,
            provider=self.name,
            raw=data,
        )
