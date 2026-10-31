"""Which Claude route the bot uses: Vercel AI Gateway when its key is set, otherwise the Anthropic API."""
import json
from types import SimpleNamespace

from bot.ai import GATEWAY_URL, ClaudeReader, gateway_model
from bot.config import Settings


def test_gateway_model_names():
    assert gateway_model("claude-opus-5-5") == "anthropic/claude-opus-5.5"
    assert gateway_model("claude-haiku-4-5") == "anthropic/claude-haiku-4.5"
    assert gateway_model("claude-sonnet-5") == "anthropic/claude-sonnet-5"
    assert gateway_model("anthropic/claude-opus-5.5-fast") == "anthropic/claude-opus-5.5-fast"


class Recorder:
    def __init__(self):
        self.calls = []
        reply = SimpleNamespace(stop_reason="end_turn", _request_id="req_test",
                                content=[SimpleNamespace(type="text", text=json.dumps({"ok": True}))])
        create = lambda **kw: self.calls.append(kw) or reply
        self.messages = SimpleNamespace(create=lambda **kw: create(route="standard", **kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: create(route="beta", **kw)))


def test_gateway_key_routes_through_vercel(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-also-present")
    reader = ClaudeReader("claude-opus-5-5", gateway_key="vck_test")
    assert reader.route == "Vercel AI Gateway" and reader.model == "anthropic/claude-opus-5.5"
    assert str(reader.client.base_url).rstrip("/") == GATEWAY_URL and reader.client.api_key == "vck_test"
    reader.client = Recorder()
    assert reader._ask("system", [{"type": "text", "text": "hi"}], {"type": "object"}) == {"ok": True}
    call = reader.client.calls[0]
    assert call["route"] == "standard" and call["model"] == "anthropic/claude-opus-5.5"
    assert "betas" not in call and "fallbacks" not in call
    assert call["output_config"]["format"]["type"] == "json_schema" and call["output_config"]["effort"] == "high"


def test_without_gateway_key_uses_anthropic_with_fallbacks(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    reader = ClaudeReader("claude-opus-5-5")
    assert reader.route == "Anthropic API" and reader.model == "claude-opus-5-5"
    reader.client = Recorder()
    reader._ask("system", [{"type": "text", "text": "hi"}], {"type": "object"})
    call = reader.client.calls[0]
    assert call["route"] == "beta" and call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]


def test_either_key_satisfies_settings(monkeypatch):
    base = {"BOT_EMAIL_ADDRESS": "b@x.com", "BOT_EMAIL_APP_PASSWORD": "p", "SITE_URL": "https://x",
            "FAMILY_SENDERS": "A <a@x.com>"}
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    assert Settings.from_env().missing() == ["ANTHROPIC_API_KEY or AI_GATEWAY_API_KEY"]
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "vck_test")
    assert Settings.from_env().missing() == []
