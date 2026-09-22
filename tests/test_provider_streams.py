import json

import httpx
import pytest

from character_chat_local.models import ChatMessage
from character_chat_local.providers import GeminiProvider, OllamaProvider, OpenAICompatibleProvider, ProviderError
from character_chat_local.service import _collect


def event(data):
    return "data: " + json.dumps(data) + "\n\n"


@pytest.fixture
def transport(monkeypatch):
    original_client = httpx.AsyncClient
    def install(body):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, content=body)
        monkeypatch.setattr("character_chat_local.providers.httpx.AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))
        return requests
    return install


def provider(kind):
    if kind == "ollama":
        return OllamaProvider()
    if kind == "gemini":
        return GeminiProvider("test-key")
    return OpenAICompatibleProvider(provider_id=kind, api_key="test-key", base_url="https://api.example")


def response_body(kind, finish=True):
    if kind == "ollama":
        body = json.dumps({"message": {"content": "こんにちは"}, "done": False}) + "\n"
        return body + (json.dumps({"done": True, "done_reason": "stop"}) + "\n" if finish else "")
    if kind == "gemini":
        data = {"content": {"parts": [{"text": "思考", "thought": True}, {"text": "こんにちは"}]}}
        if finish:
            data["finishReason"] = "STOP"
        return event({"candidates": [data]})
    body = event({"choices": [{"delta": {"content": "こんにちは"}}]})
    body += event({"choices": [], "usage": {"total_tokens": 10}})
    return body + ("data: [DONE]\n\n" if finish else "")


@pytest.mark.parametrize("kind", ["ollama", "openai", "xai", "gemini"])
async def test_stream_protocol_and_hidden_thoughts(kind, transport):
    requests = transport(response_body(kind))
    result = await _collect(provider(kind), "small", [ChatMessage(role="user", content="hi")], 0.8)
    assert result == "こんにちは" and len(requests) == 1
    payload = json.loads(requests[0].content)
    if kind == "ollama":
        assert payload["stream"] is True and payload["options"]["temperature"] == 0.8
    elif kind != "gemini":
        assert payload["stream"] is True


@pytest.mark.parametrize("kind", ["ollama", "openai", "xai", "gemini"])
async def test_truncated_stream_is_not_accepted(kind, transport):
    transport(response_body(kind, finish=False))
    with pytest.raises(ProviderError, match="before completion"):
        await _collect(provider(kind), "small", [ChatMessage(role="user", content="hi")], 0.8)


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
async def test_in_stream_error_does_not_pass_as_reply(kind, transport):
    body = json.dumps({"error": "secret-canary"})
    transport(body + "\n" if kind == "ollama" else "data: " + body + "\n\n")
    with pytest.raises(ProviderError) as error:
        await _collect(provider(kind), "small", [ChatMessage(role="user", content="hi")], 0.8)
    assert "secret-canary" not in str(error.value)
