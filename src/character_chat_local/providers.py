from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from .models import ChatMessage, ModelInfo


class ProviderError(RuntimeError):
    pass


class AIProvider(ABC):
    id: str

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    @abstractmethod
    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        raise NotImplementedError


class OllamaProvider(AIProvider):
    id = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/tags")
        response.raise_for_status()
        return [
            ModelInfo(
                id=item["name"],
                provider=self.id,
                display_name=item.get("name"),
                metadata={"size": item.get("size"), "details": item.get("details", {})},
            )
            for item in response.json().get("models", [])
        ]

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    text = data.get("message", {}).get("content", "")
                    if text:
                        yield text


class OpenAICompatibleProvider(AIProvider):
    def __init__(
        self,
        *,
        provider_id: str,
        api_key: str,
        base_url: str,
        timeout: float = 300.0,
    ):
        self.id = provider_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/v1/models", headers=self.headers)
        response.raise_for_status()
        return [
            ModelInfo(id=item["id"], provider=self.id, display_name=item.get("id"), metadata=item)
            for item in response.json().get("data", [])
        ]

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=self.headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    data = json.loads(raw)
                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta


class GeminiProvider(AIProvider):
    id = "gemini"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout: float = 300.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/v1beta/models", headers=self.headers)
        response.raise_for_status()
        result: list[ModelInfo] = []
        for item in response.json().get("models", []):
            model_id = item.get("name", "").removeprefix("models/")
            if model_id:
                result.append(
                    ModelInfo(
                        id=model_id,
                        provider=self.id,
                        display_name=item.get("displayName") or model_id,
                        metadata=item,
                    )
                )
        return result

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        system_parts = [m.content for m in messages if m.role == "system"]
        contents = []
        for message in messages:
            if message.role == "system":
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
        payload: dict[str, object] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        url = f"{self.base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=self.headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    data = json.loads(raw)
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            yield text


class ProviderRegistry:
    def __init__(self, providers: list[AIProvider] | None = None):
        self._providers = {provider.id: provider for provider in providers or []}

    def add(self, provider: AIProvider) -> None:
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> AIProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise ProviderError(f"provider is not configured: {provider_id}") from exc

    def ids(self) -> list[str]:
        return sorted(self._providers)

    @classmethod
    def from_env(cls) -> "ProviderRegistry":
        registry = cls(
            [OllamaProvider(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))]
        )
        if key := os.getenv("OPENAI_API_KEY"):
            registry.add(
                OpenAICompatibleProvider(
                    provider_id="openai",
                    api_key=key,
                    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com"),
                )
            )
        if key := os.getenv("XAI_API_KEY"):
            registry.add(
                OpenAICompatibleProvider(
                    provider_id="xai",
                    api_key=key,
                    base_url=os.getenv("XAI_BASE_URL", "https://api.x.ai"),
                )
            )
        if key := os.getenv("GEMINI_API_KEY"):
            registry.add(GeminiProvider(api_key=key))
        return registry
