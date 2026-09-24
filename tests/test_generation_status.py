import pytest

from character_chat_local.storage import ConversationConflict, Storage


def test_generation_lifecycle_is_terminal_and_blocks_parallel_start(setup_chat):
    storage, _character, conversation = setup_chat
    generation = storage.start_generation(conversation, "fake", "small")
    assert generation.status == "generating"

    with pytest.raises(ConversationConflict, match="already generating"):
        storage.start_generation(conversation, "fake", "small")

    stopped = storage.finish_generation(
        generation.id, "stopped", error_code="cancelled"
    )
    assert stopped.status == "stopped"
    assert stopped.error_code == "cancelled"

    # Repeating the same terminal transition is idempotent.
    assert storage.finish_generation(generation.id, "stopped").status == "stopped"
    with pytest.raises(ConversationConflict, match="already finished"):
        storage.finish_generation(generation.id, "completed")


def test_restart_marks_orphaned_generation_failed(tmp_path):
    path = tmp_path / "chat.db"
    storage = Storage(path)
    from character_chat_local.models import CharacterCore

    character = CharacterCore(name="Restart")
    storage.save_character(character)
    conversation = storage.create_conversation(character.id)
    generation = storage.start_generation(conversation, "fake", "small")

    reopened = Storage(path)
    failed = reopened.get_generation(generation.id)
    assert failed.status == "failed"
    assert failed.error_code == "server_restart"
