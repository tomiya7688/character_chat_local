from character_chat_local.models import CharacterCore
from character_chat_local.storage import Storage


def test_character_roundtrip(tmp_path):
    storage = Storage(tmp_path / "test.db")
    character = CharacterCore(name="Mika")
    storage.save_character(character)
    loaded = storage.load_character(character.id)
    assert loaded is not None
    assert loaded.name == "Mika"
