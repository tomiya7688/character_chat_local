import pytest

from character_chat_local.models import CharacterCore, ModelInfo
from character_chat_local.providers import AIProvider
from character_chat_local.storage import Storage


class ScriptedProvider(AIProvider):
    id = "fake"

    def __init__(self, replies=None):
        self.replies = replies or ["こんにちは。"]
        self.calls = []
        self.closed = 0

    async def list_models(self):
        return [
            ModelInfo(id="small", provider=self.id),
            ModelInfo(id="other", provider=self.id),
        ]

    async def stream_chat(self, *, model, messages, temperature=0.8):
        index = len(self.calls)
        self.calls.append((model, messages))
        try:
            reply = self.replies[min(index, len(self.replies) - 1)]
            if isinstance(reply, BaseException):
                raise reply
            yield reply
        finally:
            self.closed += 1


@pytest.fixture
def setup_chat(tmp_path):
    storage = Storage(tmp_path / "test.db")
    character = CharacterCore(name="ミカ", first_person="私", lore=["海辺の町に住む"])
    storage.save_character(character)
    conversation = storage.create_conversation(character.id)
    return storage, character, conversation


@pytest.fixture
def provider():
    return ScriptedProvider()
