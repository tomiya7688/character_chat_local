import asyncio
import json

import pytest
from conftest import ScriptedProvider

from character_chat_local.knowledge import KnowledgeExtractor
from character_chat_local.models import (
    CharacterCore,
    ChatMessage,
    DynamicStateCandidate,
    KnowledgeExtractionResult,
    RelationshipCandidate,
    TaskAssignment,
)
from character_chat_local.providers import AIProvider, ProviderRegistry
from character_chat_local.service import ChatService, QualityRejected
from character_chat_local.state import StateCandidateCommitter
from character_chat_local.storage import Storage
from character_chat_local.task_router import TaskRouter


async def test_deterministic_extractor_separates_long_term_and_current_state():
    character = CharacterCore(name="ミカ")
    result = await KnowledgeExtractor().extract(
        character=character,
        user_message=(
            "明日、東京駅で「OpenAI」の話をする。今は東京駅にいる。"
            "コーヒーが好き。私の名前は太郎。あなたは親友だよ。"
            "少し不安。これ覚えておいて？"
        ),
        final_assistant_message="私は海が好き。明日も話そう。",
    )

    assert result.strategy == "deterministic-v1"
    assert any(item.name == "OpenAI" for item in result.entities)
    assert any(
        item.source_role == "user"
        and item.epistemic_state == "confirmed"
        and item.predicate == "explicit_memory"
        for item in result.facts
    )
    assert any(
        item.value == "コーヒー"
        and item.sentiment == "like"
        and item.source_role == "user"
        for item in result.preferences
    )
    assert any(item.alias == "太郎" for item in result.aliases)
    assert any(
        item.source_role == "user" and item.time_reference == "明日"
        for item in result.events
    )
    assert any(
        item.owner == "user" and item.key == "location" and item.value == "東京駅"
        for item in result.current_state_candidates
    )
    assert any(
        item.owner == "user" and item.key == "emotion"
        for item in result.current_state_candidates
    )
    assert any(
        item.dimension == "relationship"
        and item.source_role == "user"
        and item.epistemic_state == "confirmed"
        for item in result.relationship_candidates
    )
    assert any(
        item.subject == "ミカ"
        and item.source_role == "assistant"
        and item.epistemic_state == "inferred"
        for item in result.preferences
    )


async def test_task_routed_model_extraction_and_parse_fallback():
    model_payload = {
        "entities": [
            {
                "name": "灯台",
                "source_role": "user",
                "epistemic_state": "confirmed",
                "confidence": 0.9,
            }
        ],
        "facts": [],
        "relations": [],
        "events": [],
        "preferences": [],
        "aliases": [],
        "current_state_candidates": [],
        "relationship_candidates": [],
    }
    provider = ScriptedProvider([json.dumps(model_payload, ensure_ascii=False)])
    registry = ProviderRegistry([provider])
    router = TaskRouter(registry)
    router.set_assignment(
        "knowledge_extractor",
        TaskAssignment(provider_id="fake", model="small"),
    )
    extractor = KnowledgeExtractor(router)

    result = await extractor.extract(
        character=CharacterCore(name="ミカ"),
        user_message="灯台の話",
        final_assistant_message="うん。",
    )
    assert result.strategy == "model-v1"
    assert result.entities[0].name == "灯台"
    assert len(provider.calls) == 1

    bad_provider = ScriptedProvider(["not-json"])
    bad_router = TaskRouter(ProviderRegistry([bad_provider]))
    bad_router.set_assignment(
        "knowledge_extractor",
        TaskAssignment(provider_id="fake", model="small"),
    )
    fallback = await KnowledgeExtractor(bad_router).extract(
        character=CharacterCore(name="ミカ"),
        user_message="コーヒーが好き。これ覚えて。",
        final_assistant_message="覚えておくね。",
    )
    assert fallback.strategy == "model-fallback-v1"
    assert fallback.fallback_reason == "parse_error"
    assert any(item.value == "コーヒー" for item in fallback.preferences)


def test_task_router_can_load_knowledge_model_from_environment(monkeypatch):
    provider = ScriptedProvider()
    registry = ProviderRegistry([provider])
    monkeypatch.setenv("CHARACTER_CHAT_TASK_KNOWLEDGE_EXTRACTOR_PROVIDER", "fake")
    monkeypatch.setenv("CHARACTER_CHAT_TASK_KNOWLEDGE_EXTRACTOR_MODEL", "other")
    monkeypatch.setenv("CHARACTER_CHAT_TASK_KNOWLEDGE_EXTRACTOR_TEMPERATURE", "0.2")

    router = TaskRouter.from_env(registry)
    resolved = router.resolve("knowledge_extractor")
    assert resolved is not None
    task_provider, assignment = resolved
    assert task_provider is provider
    assert assignment.model == "other"
    assert assignment.temperature == 0.2


def test_state_rule_check_commits_sources_and_clamps_relationship_jump(tmp_path):
    storage = Storage(tmp_path / "state.db")
    character = CharacterCore(name="ミカ")
    storage.save_character(character)
    conversation = storage.create_conversation(character.id)
    user_id = storage.add_message(
        conversation, ChatMessage(role="user", content="今は東京駅にいる")
    )
    assistant_id = storage.add_message(
        conversation,
        ChatMessage(role="assistant", content="私たちは親友だね"),
        "fake",
        "small",
    )

    extraction = KnowledgeExtractionResult(
        strategy="deterministic-v1",
        current_state_candidates=[
            DynamicStateCandidate(
                owner="user",
                key="location",
                value="東京駅",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.95,
            ),
            DynamicStateCandidate(
                owner="character",
                key="emotion",
                value="joy",
                source_role="assistant",
                epistemic_state="hypothesis",
                confidence=0.9,
            ),
        ],
        relationship_candidates=[
            RelationshipCandidate(
                dimension="trust",
                label="sudden trust claim",
                delta=1.0,
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.95,
            )
        ],
    )
    committer = StateCandidateCommitter(storage)
    first = committer.commit(
        character_id=character.id,
        extraction=extraction,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )

    assert len(first.dynamic_states) == 1
    assert first.dynamic_states[0].source_message_id == user_id
    assert len(first.relationship_states) == 1
    assert first.relationship_states[0].score == pytest.approx(0.08)
    assert first.relationship_states[0].source_message_id == user_id
    assert any(reason.startswith("hypothesis_state") for reason in first.rejected)

    second_extraction = KnowledgeExtractionResult(
        strategy="deterministic-v1",
        relationship_candidates=[
            RelationshipCandidate(
                dimension="trust",
                label="assistant trust signal",
                delta=1.0,
                source_role="assistant",
                epistemic_state="inferred",
                confidence=0.8,
            )
        ],
    )
    second = committer.commit(
        character_id=character.id,
        extraction=second_extraction,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    assert second.relationship_states[0].score == pytest.approx(0.11)
    history = storage.relationship_state_history(character.id)
    assert len(history) == 2
    assert history[0].change_id != history[1].change_id


async def test_final_turn_persists_extraction_state_and_reinjects_next_context(
    setup_chat,
):
    storage, character, conversation = setup_chat
    service = ChatService(storage)
    first_provider = ScriptedProvider(["大丈夫。"])

    result = await service.run(
        provider=first_provider,
        model="small",
        character=character,
        conversation_id=conversation,
        user_input=(
            "今は東京駅にいる。少し不安。あなたは親友だよ。"
            "コーヒーが好き。これ覚えておいて。"
        ),
    )
    assert result.guardian.passed

    messages = storage.list_message_records(conversation, tail=True)
    assert len(messages) == 2
    extraction_records = storage.list_knowledge_extractions(conversation)
    assert len(extraction_records) == 1
    record = extraction_records[0]
    assert record.user_message_id == messages[0].id
    assert record.assistant_message_id == messages[1].id
    assert record.extraction.facts
    assert record.extraction.preferences

    states = storage.latest_dynamic_states(character.id)
    assert any(
        item.owner == "user" and item.key == "location" and item.value == "東京駅"
        for item in states
    )
    relationships = storage.latest_relationship_states(character.id)
    assert relationships
    assert all(abs(item.score) <= 0.08 for item in relationships)

    memory_step = next(
        item for item in result.trace.steps if item.name == "memory_extraction"
    )
    state_step = next(
        item for item in result.trace.steps if item.name == "state_update"
    )
    assert memory_step.status == "completed"
    assert state_step.status == "completed"

    second_provider = ScriptedProvider(["続けよう。"])
    await service.run(
        provider=second_provider,
        model="small",
        character=character,
        conversation_id=conversation,
        user_input="今の状況から続けよう",
    )
    system_prompt = second_provider.calls[0][1][0].content
    assert "user.location: 東京駅" in system_prompt


async def test_failed_or_cancelled_turn_never_persists_extraction(setup_chat):
    storage, character, conversation = setup_chat
    service = ChatService(storage)

    with pytest.raises(QualityRejected):
        await service.run(
            provider=ScriptedProvider(["AIとして回答します。"]),
            model="small",
            character=character,
            conversation_id=conversation,
            user_input="覚えておいて",
        )
    assert storage.list_knowledge_extractions(conversation) == []
    assert storage.latest_dynamic_states(character.id) == []
    assert storage.latest_relationship_states(character.id) == []

    class SlowProvider(AIProvider):
        id = "slow"

        def __init__(self):
            self.started = asyncio.Event()

        async def list_models(self):
            return []

        async def stream_chat(self, **kwargs):
            self.started.set()
            await asyncio.Event().wait()
            yield "unused"

    slow = SlowProvider()
    task = asyncio.create_task(
        service.run(
            provider=slow,
            model="small",
            character=character,
            conversation_id=conversation,
            user_input="今は東京駅にいる",
        )
    )
    await slow.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert storage.list_messages(conversation) == []
    assert storage.list_knowledge_extractions(conversation) == []
