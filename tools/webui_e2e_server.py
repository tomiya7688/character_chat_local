"""Disposable E2E server. Real API/SQLite; deterministic provider, never a live LLM."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from character_chat_local.api import create_app
from character_chat_local.models import CharacterCore, ChatMessage, ModelInfo
from character_chat_local.providers import AIProvider, ProviderError, ProviderRegistry

TOKEN = "webui-test-token"  # Test fixture only; not a real credential.
workspace = tempfile.TemporaryDirectory(prefix="character-chat-webui-")


class TestProvider(AIProvider):
    def __init__(self, provider_id: str):
        self.id = provider_id
        self.repairs: set[str] = set()

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id=model, provider=self.id)
            for model in ["test-small", "test-alt", "repair-model", "offline"]
        ]

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        user = next(
            message.content for message in reversed(messages) if message.role == "user"
        )
        await asyncio.sleep(0.2)
        if model == "offline":
            raise ProviderError("DO_NOT_LEAK_PROVIDER_DETAIL")
        if "拒否テスト" in user:
            yield "As an AI, I cannot act as a character."
            return
        if model == "repair-model" and user not in self.repairs:
            self.repairs.add(user)
            yield "As an AI, I cannot act as a character."
            return
        if user == "表示テスト":
            yield (
                "## 見出し\n\n**強調された文章**\n\n```python\nprint('hello')\n```\n\n"
                '<img src="x" onerror="window.__xss=true">\n\n'
                "[危険リンク](javascript:alert(1))\n\n"
                "![外部画像](https://example.invalid/tracker.png)"
            )
            return
        yield f"[{model}] {user} を受け取ったよ。"


app = create_app(
    database_path=Path(workspace.name) / "chat.db",
    registry=ProviderRegistry([TestProvider("ollama"), TestProvider("local-test")]),
    api_token=TOKEN,
)
base_lifespan = app.router.lifespan_context


@asynccontextmanager
async def seeded_lifespan(app):
    async with base_lifespan(app):
        storage = app.state.storage
        history_character = CharacterCore(id="fixture-history", name="履歴テスト")
        storage.save_character(history_character)
        conversation_id = storage.create_conversation(history_character.id)
        other_id = storage.create_conversation(history_character.id)
        with storage.session() as db:
            for i in range(2000):
                storage._insert_message(
                    db,
                    conversation_id,
                    ChatMessage(
                        role="user" if i % 2 == 0 else "assistant",
                        content=f"履歴 {i:04d}",
                    ),
                    "ollama" if i % 2 else None,
                    "test-small" if i % 2 else None,
                )
                if i % 50 == 0:
                    storage._insert_message(
                        db, other_id, ChatMessage(role="user", content="別会話")
                    )
        app.state.history_fixture = conversation_id
        yield


app.router.lifespan_context = seeded_lifespan


@app.get("/e2e/history")
def fixture_history():
    return {"conversation_id": app.state.history_fixture}
