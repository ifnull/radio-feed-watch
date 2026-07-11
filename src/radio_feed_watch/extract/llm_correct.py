"""Optional LLM post-correction for bad STT in radio context.

OpenAI-compatible Chat Completions API (OpenAI, Azure, local proxies, etc.).
Gated: only short / low-confidence clips by default. Prefer leave-unchanged.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import httpx

from radio_feed_watch.config import LlmCorrectConfig
from radio_feed_watch.filters import normalize_text

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


@dataclass
class LlmCorrectResult:
    text: str
    changed: bool
    from_text: str | None = None
    to_text: str | None = None
    intent: str | None = None
    confidence: float | None = None
    reason: str | None = None
    skipped: str | None = None  # why we did not call / did not apply


def should_llm_correct(
    *,
    text: str,
    duration_s: float | None,
    confidence: float | None,
    cfg: LlmCorrectConfig,
    api_key: str,
    short_ack_changed: bool = False,
) -> tuple[bool, str | None]:
    """Return (should_call, skip_reason)."""
    if not cfg.enabled:
        return False, "disabled"
    if not (api_key or "").strip():
        return False, "no_api_key"
    if cfg.skip_if_short_ack and short_ack_changed:
        return False, "short_ack_already"

    norm = normalize_text(text)
    if not norm:
        return False, "empty"

    words = norm.split()
    word_count = len(words)

    reasons: list[str] = []
    if duration_s is not None and duration_s <= cfg.max_duration_s:
        reasons.append(f"short_clip<={cfg.max_duration_s}s")
    if (
        cfg.max_confidence is not None
        and confidence is not None
        and confidence < cfg.max_confidence
    ):
        reasons.append(f"low_conf<{cfg.max_confidence}")
    if word_count <= cfg.max_words:
        reasons.append(f"few_words<={cfg.max_words}")

    if not reasons:
        return False, "gate_not_met"
    return True, ",".join(reasons)


def _system_prompt(locale_label: str, locale_hints: str) -> str:
    return f"""You correct police/fire radio STT errors for {locale_label}.

Context: scanner audio, ten-codes, unit IDs, street/highway names. STT often
mangles short acks (Never/Shower/Tower → ten-four / 10-4) and proper nouns.

Rules:
- Prefer leaving the transcript unchanged when unsure.
- Never invent house numbers, unit IDs, names, or streets not supported by the audio text.
- You may normalize spoken ten-codes (ten four → 10-4) and obvious radio slang.
- Use recent talkgroup lines only as context, not as facts to copy.
{locale_hints}

Respond with ONLY JSON (no markdown):
{{"corrected_text":"...","changed":true|false,"intent":"ack|dispatch|status|location|other|unknown","confidence":0.0-1.0,"reason":"brief"}}
"""


def _parse_llm_json(content: str) -> dict[str, Any] | None:
    raw = (content or "").strip()
    if not raw:
        return None
    m = _JSON_FENCE_RE.search(raw)
    if m:
        raw = m.group(1).strip()
    # Tolerate leading/trailing junk around a JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class LlmCorrector:
    """Async OpenAI-compatible corrector with per-source recent context."""

    def __init__(
        self,
        cfg: LlmCorrectConfig,
        *,
        api_key: str,
        locale_label: str,
        locale_hints: str = "",
    ):
        self.cfg = cfg
        self.api_key = (api_key or "").strip()
        self.locale_label = locale_label
        self.locale_hints = locale_hints
        self._recent: dict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=max(1, cfg.context_size))
        )

    def remember(self, source_id: str, text: str) -> None:
        t = text.strip()
        if t:
            self._recent[source_id].append(t)

    def context_lines(self, source_id: str) -> list[str]:
        return list(self._recent.get(source_id, ()))

    async def correct(
        self,
        *,
        text: str,
        source_id: str,
        duration_s: float | None,
        confidence: float | None,
        short_ack_changed: bool = False,
    ) -> LlmCorrectResult:
        ok, reason = should_llm_correct(
            text=text,
            duration_s=duration_s,
            confidence=confidence,
            cfg=self.cfg,
            api_key=self.api_key,
            short_ack_changed=short_ack_changed,
        )
        if not ok:
            return LlmCorrectResult(text=text, changed=False, skipped=reason)

        recent = self.context_lines(source_id)
        user_payload = {
            "transcript": text.strip(),
            "duration_s": duration_s,
            "stt_confidence": confidence,
            "recent_same_source": recent,
        }
        try:
            data = await self._chat(user_payload)
        except Exception as e:
            logger.warning("[%s] llm_correct failed: %s", source_id, e)
            return LlmCorrectResult(text=text, changed=False, skipped=f"error:{e}")

        if not data:
            return LlmCorrectResult(text=text, changed=False, skipped="bad_json")

        corrected = str(data.get("corrected_text") or "").strip()
        changed_flag = bool(data.get("changed"))
        conf = data.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        intent = data.get("intent")
        intent_s = str(intent) if intent is not None else None
        reason_s = str(data.get("reason") or "") or None

        if not corrected:
            return LlmCorrectResult(
                text=text,
                changed=False,
                skipped="empty_correction",
                intent=intent_s,
                confidence=conf_f,
                reason=reason_s,
            )

        if not changed_flag or normalize_text(corrected) == normalize_text(text):
            return LlmCorrectResult(
                text=text,
                changed=False,
                skipped="unchanged",
                intent=intent_s,
                confidence=conf_f,
                reason=reason_s,
            )

        if conf_f is not None and conf_f < self.cfg.min_correct_confidence:
            return LlmCorrectResult(
                text=text,
                changed=False,
                skipped=f"low_llm_conf<{self.cfg.min_correct_confidence}",
                intent=intent_s,
                confidence=conf_f,
                reason=reason_s,
                from_text=text.strip(),
                to_text=corrected,
            )

        return LlmCorrectResult(
            text=corrected,
            changed=True,
            from_text=text.strip(),
            to_text=corrected,
            intent=intent_s,
            confidence=conf_f,
            reason=reason_s,
        )

    async def _chat(self, user_payload: dict[str, Any]) -> dict[str, Any] | None:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": _system_prompt(self.locale_label, self.locale_hints),
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
        }
        async with httpx.AsyncClient(timeout=self.cfg.timeout_s) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        return _parse_llm_json(content)
