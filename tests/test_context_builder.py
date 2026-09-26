import json

import pytest

from character_chat_local.models import (
    CharacterCore,
    ChatMessage,
    ConversationSummary,
    MemoryRecord,
    RecallHit,
    SummaryEntry,
)
from character_chat_local.prompting import (
    CONTEXT_ORDER,
    ContextBudgetError,
    build_context,
    prompt_tokens,
)


def hit(memory: MemoryRecord, score: float = 0.8) -> RecallHit:
    return RecallHit(memory=memory, score=score, reasons=["test"])


def system_payload(result):
    return json.loads(result.messages[0].content.split("\n", 1)[1])


def test_context_order_and_memory_labels_are_explicit():
    character = CharacterCore(
        name="ミカ",
        first_person="私",
        personality=["穏やか"],
        lore=["海辺の町に住む"],
        relationship=["幼なじみ"],
    )
    canon = MemoryRecord(
        character_id=character.id,
        type="canon",
        content="灯台は町の北側にある",
    )
    relationship = MemoryRecord(
        character_id=character.id,
        type="relationship",
        content="最近は少し打ち解けている",
        importance=0.9,
    )
    state = MemoryRecord(
        character_id=character.id,
        type="current_state",
        content="今は港にいる",
        importance=0.9,
    )
    fact = MemoryRecord(
        character_id=character.id,
        type="user_fact",
        content="ユーザーは紅茶が好き",
    )
    inferred = MemoryRecord(
        character_id=character.id,
        type="inferred_fact",
        content="ユーザーは雨が苦手かもしれない",
        confidence=0.5,
    )
    summary = ConversationSummary(
        entries=[
            SummaryEntry(
                source_message_id="old-user",
                position=1,
                role="user",
                excerpt="昔、港へ行ったと話した",
                priority=1,
            )
        ]
    )
    result = build_context(
        character=character,
        history=[
            ChatMessage(role="user", content="さっきの続き"),
            ChatMessage(role="assistant", content="うん、続けよう"),
        ],
        user_input="灯台の話をしよう",
        recalled=[hit(canon), hit(fact), hit(inferred)],
        summary=summary,
        memories=[canon, relationship, state, fact, inferred],
        max_prompt_bytes=100_000,
        max_prompt_tokens=20_000,
    )

    payload = system_payload(result)
    assert payload["context_order"] == list(CONTEXT_ORDER)
    assert [section["name"] for section in payload["context_sections"]] == list(
        CONTEXT_ORDER[:-1]
    )
    assert result.messages[-1] == ChatMessage(role="user", content="灯台の話をしよう")

    sections = {
        section["name"]: section["items"] for section in payload["context_sections"]
    }
    assert any(
        item.get("source_type") == "character_lore" and item["label"] == "FACT"
        for item in sections["critical_lore"]
    )
    assert any(
        item.get("source_type") == "canon" and item["label"] == "FACT"
        for item in sections["critical_lore"]
    )
    assert {item["label"] for item in sections["relationship_state"]} == {
        "RELATIONSHIP"
    }
    assert {item["label"] for item in sections["current_state"]} == {"STATE"}
    assert {item["label"] for item in sections["relevant_memories"]} == {
        "FACT",
        "INFERRED",
    }
    assert sections["recent_conversation"][0]["label"] == "CONVERSATION"


def test_context_budget_drops_optional_whole_records_and_reports_debug():
    character = CharacterCore(
        name="Budget",
        lore=["固定Lore"],
        relationship=["固定関係"],
    )
    baseline = build_context(
        character=character,
        history=[],
        user_input="現在の質問",
        recalled=[],
        memories=[],
        max_prompt_bytes=100_000,
        max_prompt_tokens=20_000,
    )
    tight_tokens = baseline.debug.estimated_tokens + 120

    memories = [
        MemoryRecord(
            character_id=character.id,
            type="user_fact" if index % 2 == 0 else "inferred_fact",
            content=f"memory-{index}-" + ("長い内容" * 30),
            importance=1.0,
        )
        for index in range(8)
    ]
    recalled = [
        hit(memory, 1.0 - index * 0.01) for index, memory in enumerate(memories)
    ]
    history = [
        ChatMessage(role=role, content=f"history-{index}-" + ("会話" * 30))
        for index in range(8)
        for role in ("user", "assistant")
    ]

    result = build_context(
        character=character,
        history=history,
        user_input="現在の質問",
        recalled=recalled,
        memories=memories,
        max_prompt_bytes=100_000,
        max_prompt_tokens=tight_tokens,
    )

    assert result.debug.order == list(CONTEXT_ORDER)
    assert result.debug.estimated_tokens <= tight_tokens
    assert prompt_tokens(result.messages) <= tight_tokens
    assert sum(section.dropped_items for section in result.debug.sections) > 0
    assert result.messages[-1].content == "現在の質問"
    assert "固定Lore" in result.messages[0].content
    assert "固定関係" in result.messages[0].content

    payload_text = result.messages[0].content
    for memory in memories:
        prefix = memory.content[:18]
        if prefix in payload_text:
            assert memory.content in payload_text


def test_required_context_is_not_silently_truncated():
    character = CharacterCore(
        name="Required",
        lore=["絶対に保持するLore" * 20],
        relationship=["固定関係"],
    )
    baseline = build_context(
        character=character,
        history=[],
        user_input="現在入力",
        recalled=[],
        memories=[],
        max_prompt_bytes=100_000,
        max_prompt_tokens=20_000,
    )

    with pytest.raises(ContextBudgetError, match="exceed context budget"):
        build_context(
            character=character,
            history=[],
            user_input="現在入力",
            recalled=[],
            memories=[],
            max_prompt_bytes=100_000,
            max_prompt_tokens=baseline.debug.estimated_tokens - 1,
        )


def test_context_debug_tracks_recent_conversation_selection():
    character = CharacterCore(name="Debug")
    result = build_context(
        character=character,
        history=[
            ChatMessage(role="user", content="質問1"),
            ChatMessage(role="assistant", content="返答1"),
        ],
        user_input="質問2",
        recalled=[],
        memories=[],
        max_prompt_bytes=100_000,
        max_prompt_tokens=20_000,
    )
    recent = next(
        section
        for section in result.debug.sections
        if section.name == "recent_conversation"
    )
    assert recent.selected_items == 2
    assert recent.used_tokens > 0
    assert "CONVERSATION" in recent.labels
