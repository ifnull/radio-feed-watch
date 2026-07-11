"""Transcript quality gates: length, confidence, noise phrases, near-dedupe."""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from difflib import SequenceMatcher

from radio_feed_watch.config import FilterConfig

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    t = text.lower().strip()
    t = _PUNCT_RE.sub(" ", t)
    t = _SPACE_RE.sub(" ", t).strip()
    return t


@dataclass
class GateResult:
    ok: bool
    reason: str | None = None


class TranscriptDeduper:
    """Per-source sliding window of recent normalized transcripts."""

    def __init__(self, window_s: float, similarity: float):
        self.window_s = window_s
        self.similarity = similarity
        self._recent: dict[str, deque[tuple[float, str]]] = defaultdict(deque)

    def _prune(self, source_id: str, now: float) -> None:
        q = self._recent[source_id]
        cutoff = now - self.window_s
        while q and q[0][0] < cutoff:
            q.popleft()

    def is_duplicate(self, source_id: str, text: str, now: float | None = None) -> bool:
        if self.window_s <= 0:
            return False
        now = time.monotonic() if now is None else now
        norm = normalize_text(text)
        if not norm:
            return False
        self._prune(source_id, now)
        for _ts, prev in self._recent[source_id]:
            if prev == norm:
                return True
            if self.similarity < 1.0 and SequenceMatcher(None, prev, norm).ratio() >= self.similarity:
                return True
        return False

    def remember(self, source_id: str, text: str, now: float | None = None) -> None:
        if self.window_s <= 0:
            return
        now = time.monotonic() if now is None else now
        norm = normalize_text(text)
        if not norm:
            return
        self._prune(source_id, now)
        self._recent[source_id].append((now, norm))


@dataclass
class AckRemapResult:
    text: str
    changed: bool
    from_text: str | None = None
    to_text: str | None = None


def remap_short_ack(
    *,
    text: str,
    duration_s: float | None,
    filters: FilterConfig,
) -> AckRemapResult:
    """
    Map common short-burst ASR misses of 'ten-four' → 'ten four'.

    Only applies to very short clips with 1–2 word transcripts that exactly match
    the junk lexicon (never/shower/tower/…). Heuristic — not perfect.
    """
    if not filters.short_ack_remap:
        return AckRemapResult(text=text, changed=False)

    if duration_s is not None and duration_s > filters.short_ack_max_duration_s:
        return AckRemapResult(text=text, changed=False)

    norm = normalize_text(text)
    if not norm:
        return AckRemapResult(text=text, changed=False)

    words = norm.split()
    if len(words) > filters.short_ack_max_words:
        return AckRemapResult(text=text, changed=False)

    # Exact phrase match against map keys (already normalized keys preferred)
    replacement = filters.short_ack_map.get(norm)
    if replacement is None:
        # also try single-word if multi-word junk somehow
        if len(words) == 1:
            replacement = filters.short_ack_map.get(words[0])
    if not replacement:
        return AckRemapResult(text=text, changed=False)

    return AckRemapResult(
        text=replacement,
        changed=True,
        from_text=text.strip(),
        to_text=replacement,
    )


def evaluate_transcript(
    *,
    text: str,
    confidence: float | None,
    filters: FilterConfig,
    source_id: str,
    deduper: TranscriptDeduper,
) -> GateResult:
    raw = text.strip()
    if not raw:
        return GateResult(False, "empty")

    if len(raw) < filters.min_text_chars:
        return GateResult(False, f"short<{filters.min_text_chars}")

    norm = normalize_text(raw)
    if not norm:
        return GateResult(False, "empty_normalized")

    for phrase in filters.drop_phrases:
        p = normalize_text(phrase)
        if p and norm == p:
            return GateResult(False, f"noise_phrase:{phrase}")

    if (
        filters.min_confidence is not None
        and confidence is not None
        and confidence < filters.min_confidence
    ):
        return GateResult(False, f"low_confidence<{filters.min_confidence}")

    if deduper.is_duplicate(source_id, raw):
        return GateResult(False, "duplicate")

    return GateResult(True)


def should_skip_clip(*, duration_s: float | None, filters: FilterConfig) -> GateResult:
    if duration_s is not None and duration_s < filters.min_clip_duration_s:
        return GateResult(False, f"short_clip<{filters.min_clip_duration_s}s")
    return GateResult(True)
