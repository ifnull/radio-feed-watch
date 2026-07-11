"""Tests for gated LLM transcript correction."""

from __future__ import annotations

import json

import httpx
import pytest

from radio_feed_watch.config import LlmCorrectConfig
from radio_feed_watch.extract.llm_correct import (
    LlmCorrector,
    _parse_llm_json,
    should_llm_correct,
)


def test_gate_disabled_and_no_key():
    cfg = LlmCorrectConfig(enabled=False)
    ok, reason = should_llm_correct(
        text="Never.", duration_s=2.0, confidence=0.2, cfg=cfg, api_key="sk"
    )
    assert not ok and reason == "disabled"

    cfg = LlmCorrectConfig(enabled=True)
    ok, reason = should_llm_correct(
        text="Never.", duration_s=2.0, confidence=0.2, cfg=cfg, api_key=""
    )
    assert not ok and reason == "no_api_key"


def test_gate_skips_short_ack_and_long_clear_clip():
    cfg = LlmCorrectConfig(enabled=True)
    ok, reason = should_llm_correct(
        text="Never.",
        duration_s=2.0,
        confidence=0.2,
        cfg=cfg,
        api_key="sk",
        short_ack_changed=True,
    )
    assert not ok and reason == "short_ack_already"

    ok, reason = should_llm_correct(
        text="Engine 5 responding to a structure fire on Congress Avenue",
        duration_s=12.0,
        confidence=0.9,
        cfg=cfg,
        api_key="sk",
    )
    assert not ok and reason == "gate_not_met"


def test_gate_matches_short_low_conf_few_words():
    cfg = LlmCorrectConfig(enabled=True, max_duration_s=4.0, max_confidence=0.5, max_words=3)

    ok, reason = should_llm_correct(
        text="Never.", duration_s=2.4, confidence=0.8, cfg=cfg, api_key="sk"
    )
    assert ok and "short_clip" in (reason or "")

    ok, reason = should_llm_correct(
        text="Units on scene for an MVC near the intersection",
        duration_s=10.0,
        confidence=0.3,
        cfg=cfg,
        api_key="sk",
    )
    assert ok and "low_conf" in (reason or "")

    ok, reason = should_llm_correct(
        text="Copy that",
        duration_s=8.0,
        confidence=0.9,
        cfg=cfg,
        api_key="sk",
    )
    assert ok and "few_words" in (reason or "")


def test_parse_llm_json_tolerates_fences():
    data = _parse_llm_json(
        '```json\n{"corrected_text":"10-4","changed":true,"confidence":0.9}\n```'
    )
    assert data and data["corrected_text"] == "10-4"


@pytest.mark.asyncio
async def test_corrector_applies_high_conf_change(monkeypatch):
    cfg = LlmCorrectConfig(enabled=True, min_correct_confidence=0.6)
    corrector = LlmCorrector(cfg, api_key="sk-test", locale_label="Austin")

    async def fake_chat(self, user_payload):
        return {
            "corrected_text": "10-4",
            "changed": True,
            "intent": "ack",
            "confidence": 0.92,
            "reason": "short ack misheard as Never",
        }

    monkeypatch.setattr(LlmCorrector, "_chat", fake_chat)
    result = await corrector.correct(
        text="Never.",
        source_id="austin",
        duration_s=2.4,
        confidence=0.4,
    )
    assert result.changed
    assert result.text == "10-4"
    assert result.intent == "ack"


@pytest.mark.asyncio
async def test_corrector_rejects_low_llm_confidence(monkeypatch):
    cfg = LlmCorrectConfig(enabled=True, min_correct_confidence=0.8)
    corrector = LlmCorrector(cfg, api_key="sk-test", locale_label="Austin")

    async def fake_chat(self, user_payload):
        return {
            "corrected_text": "maybe ten four",
            "changed": True,
            "intent": "ack",
            "confidence": 0.4,
            "reason": "guess",
        }

    monkeypatch.setattr(LlmCorrector, "_chat", fake_chat)
    result = await corrector.correct(
        text="Never.",
        source_id="austin",
        duration_s=2.0,
        confidence=0.3,
    )
    assert not result.changed
    assert result.skipped and result.skipped.startswith("low_llm_conf")
    assert result.text == "Never."


@pytest.mark.asyncio
async def test_corrector_http_roundtrip(monkeypatch):
    """Exercise _chat against a mocked OpenAI-compatible endpoint."""
    cfg = LlmCorrectConfig(
        enabled=True,
        base_url="https://example.test/v1",
        model="test-model",
        timeout_s=5.0,
    )
    corrector = LlmCorrector(cfg, api_key="sk-test", locale_label="Austin")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/chat/completions")
        body = json.loads(request.content.decode())
        assert body["model"] == "test-model"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "corrected_text": "10-4",
                                    "changed": True,
                                    "intent": "ack",
                                    "confidence": 0.95,
                                    "reason": "ack",
                                }
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "radio_feed_watch.extract.llm_correct.httpx.AsyncClient",
        PatchedClient,
    )
    result = await corrector.correct(
        text="Never.",
        source_id="austin",
        duration_s=2.0,
        confidence=0.2,
    )
    assert result.changed
    assert result.text == "10-4"


def test_config_loads_llm_correct_defaults():
    from pathlib import Path

    from radio_feed_watch.config import load_config

    app = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
    assert app.llm_correct.enabled is False
    assert app.llm_correct.model == "gpt-4.1-mini"
    assert app.llm_correct.max_words == 3
