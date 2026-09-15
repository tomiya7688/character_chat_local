from collections.abc import AsyncIterator

from character_chat_local.models import (
    CharacterCore,
    ChatMessage,
    MemoryRecord,
    ModelInfo,
)
from character_chat_local.providers import AIProvider
from character_chat_local.service import ChatService
from character_chat_local.storage import Storage


class FakeProvider(AIProvider):
    id = "fake"

    def __init__(self):
        self.calls = 0

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="fake", provider="fake")]

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.8,
    ) -> AsyncIterator[str]:
        self.calls += 1
        yield "灯台へ行こう" if self.calls == 1 else "遠くから灯台を見よう"


async def test_secondary_recall_regenerates(tmp_path):
    storage = Storage(tmp_path / "test.db")
    character = CharacterCore(name="Mika")
    memory = MemoryRecord(
        character_id=character.id,
        type="episodic",
        content="灯台には近づかない約束がある",
        triggers=["灯台"],
        importance=1.0,
    )
    storage.upsert_memory(memory)
    provider = FakeProvider()
    result = await ChatService(storage).run(
        provider=provider,
        model="fake",
        character=character,
        user_input="散歩しよう",
    )
    assert result.regenerated_for_recall
    assert provider.calls == 2
