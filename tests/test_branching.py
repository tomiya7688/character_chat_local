import pytest

from character_chat_local.models import ChatMessage
from character_chat_local.service import ChatService


def test_edit_retry_branch_copies_only_prefix_and_stays_hidden_until_commit(setup_chat):
    storage, _character, conversation_id = setup_chat
    first_user = storage.add_message(
        conversation_id, ChatMessage(role="user", content="最初の質問")
    )
    first_assistant = storage.add_message(
        conversation_id,
        ChatMessage(role="assistant", content="最初の返答"),
        "fake",
        "small",
    )
    edited_user = storage.add_message(
        conversation_id, ChatMessage(role="user", content="編集前の質問")
    )
    superseded_assistant = storage.add_message(
        conversation_id,
        ChatMessage(role="assistant", content="編集前の返答"),
        "fake",
        "small",
    )
    storage.add_message(conversation_id, ChatMessage(role="user", content="後続の質問"))
    storage.add_message(
        conversation_id,
        ChatMessage(role="assistant", content="後続の返答"),
        "fake",
        "small",
    )

    branch = storage.create_edit_retry_branch(conversation_id, edited_user)

    assert branch.pending is True
    assert branch.parent_conversation_id == conversation_id
    assert branch.forked_from_message_id == edited_user
    assert branch.supersedes_message_id == superseded_assistant
    assert branch.fork_reason == "edit_retry"
    assert branch.id not in {item.id for item in storage.list_conversations(500)}

    copied = storage.list_message_records(branch.id, tail=True)
    assert [item.content for item in copied] == ["最初の質問", "最初の返答"]
    assert [item.origin_message_id for item in copied] == [
        first_user,
        first_assistant,
    ]
    assert [item.generation_id for item in copied] == [None, None]

    original = storage.list_message_records(conversation_id, tail=True)
    assert len(original) == 6
    assert original[2].id == edited_user

    storage.discard_pending_branch(branch.id)
    with pytest.raises(KeyError, match="conversation not found"):
        storage.get_conversation(branch.id)
    assert len(storage.list_message_records(conversation_id, tail=True)) == 6


@pytest.mark.asyncio
async def test_regenerate_branch_supersedes_only_after_replacement_commits(
    setup_chat, provider
):
    storage, character, conversation_id = setup_chat
    first_user = storage.add_message(
        conversation_id, ChatMessage(role="user", content="前の質問")
    )
    first_assistant = storage.add_message(
        conversation_id,
        ChatMessage(role="assistant", content="前の返答"),
        "fake",
        "small",
    )
    provider.replies = ["元の返答です。", "再生成した返答です。"]
    service = ChatService(storage)

    original_generation = storage.start_generation(
        conversation_id, provider.id, "small"
    )
    await service.run(
        provider=provider,
        model="small",
        character=character,
        user_input="この返答をあとで再生成する",
        conversation_id=conversation_id,
        generation_id=original_generation.id,
    )
    storage.finish_generation(original_generation.id, "completed")

    original_messages = storage.list_message_records(conversation_id, tail=True)
    target = original_messages[-1]
    assert target.role == "assistant"
    assert target.generation_id == original_generation.id

    branch, retry_input = storage.create_regenerate_branch(conversation_id, target.id)
    assert retry_input == "この返答をあとで再生成する"
    assert storage.get_generation(original_generation.id).status == "completed"

    replacement_generation = storage.start_generation(branch.id, provider.id, "small")
    await service.run(
        provider=provider,
        model="small",
        character=character,
        user_input=retry_input,
        conversation_id=branch.id,
        generation_id=replacement_generation.id,
    )
    storage.finish_generation(replacement_generation.id, "completed")

    published = storage.get_conversation(branch.id)
    assert published.pending is False
    assert published.parent_conversation_id == conversation_id
    assert published.fork_reason == "regenerate"

    old_generation = storage.get_generation(original_generation.id)
    assert old_generation.status == "superseded"
    assert old_generation.superseded_by_generation_id == replacement_generation.id
    assert storage.get_generation(replacement_generation.id).status == "completed"

    source_after = storage.list_message_records(conversation_id, tail=True)
    assert [item.id for item in source_after] == [item.id for item in original_messages]
    assert source_after[-1].content == "元の返答です。"

    branch_messages = storage.list_message_records(branch.id, tail=True)
    assert [item.content for item in branch_messages] == [
        "前の質問",
        "前の返答",
        "この返答をあとで再生成する",
        "再生成した返答です。",
    ]
    assert [item.origin_message_id for item in branch_messages[:2]] == [
        first_user,
        first_assistant,
    ]
    assert branch_messages[-1].generation_id == replacement_generation.id
