from conftest import ScriptedProvider

from character_chat_local.models import CharacterCore, MemoryRecord
from character_chat_local.service import ChatService
from character_chat_local.storage import Storage


def step(trace, name):
    return [item for item in trace.steps if item.name == name]


async def test_fast_mode_stays_single_pass_even_with_inspect_signal(tmp_path):
    storage = Storage(tmp_path / "fast.db")
    character = CharacterCore(name="Fast")
    storage.upsert_memory(
        MemoryRecord(
            character_id=character.id,
            type="episodic",
            content="灯台には近づかない約束",
            triggers=["灯台"],
        )
    )
    provider = ScriptedProvider(["灯台へ行こう。"])
    result = await ChatService(storage, default_quality_mode="fast").run(
        provider=provider,
        model="small",
        character=character,
        user_input="散歩しよう",
    )

    assert result.quality_mode == "fast"
    assert len(provider.calls) == 1
    assert not result.secondary_recall.hits
    assert step(result.trace, "lightweight_check")[0].details["requires_inspection"]
    assert step(result.trace, "secondary_recall")[0].status == "skipped"
    assert step(result.trace, "guardian")[0].status == "skipped"
    assert step(result.trace, "final_guardian")[0].status == "skipped"


async def test_balanced_mode_escalates_only_when_lightweight_check_signals(tmp_path):
    storage = Storage(tmp_path / "balanced.db")
    character = CharacterCore(name="Balanced")
    storage.upsert_memory(
        MemoryRecord(
            character_id=character.id,
            type="episodic",
            content="灯台には近づかない約束",
            triggers=["灯台"],
        )
    )
    provider = ScriptedProvider(["灯台へ行こう。", "遠くから灯台を見よう。"])
    result = await ChatService(storage).run(
        provider=provider,
        model="small",
        character=character,
        user_input="散歩しよう",
    )

    assert result.quality_mode == "balanced"
    assert result.regenerated_for_recall
    assert len(provider.calls) == 2
    assert len(result.secondary_recall.hits) == 1
    assert step(result.trace, "draft_analysis")[0].status == "completed"
    assert step(result.trace, "guardian")[0].status == "completed"
    assert step(result.trace, "final_guardian")[0].status == "skipped"


async def test_balanced_mode_skips_heavy_path_for_plain_reply(tmp_path):
    storage = Storage(tmp_path / "plain.db")
    character = CharacterCore(name="Balanced")
    provider = ScriptedProvider(["今日はのんびり歩こう。"])
    result = await ChatService(storage).run(
        provider=provider,
        model="small",
        character=character,
        user_input="散歩しよう",
    )

    assert len(provider.calls) == 1
    assert step(result.trace, "draft_analysis")[0].status == "skipped"
    assert step(result.trace, "secondary_recall")[0].status == "skipped"
    assert step(result.trace, "guardian")[0].status == "skipped"


async def test_strict_mode_always_runs_analysis_guardian_and_final_guardian(tmp_path):
    storage = Storage(tmp_path / "strict.db")
    character = CharacterCore(name="Strict")
    provider = ScriptedProvider(["今日はのんびり歩こう。"])
    result = await ChatService(storage, default_quality_mode="strict").run(
        provider=provider,
        model="small",
        character=character,
        user_input="散歩しよう",
    )

    assert result.quality_mode == "strict"
    assert len(provider.calls) == 1
    assert step(result.trace, "draft_analysis")[0].status == "completed"
    assert step(result.trace, "secondary_recall")[0].status == "completed"
    assert step(result.trace, "guardian")[0].status == "completed"
    assert step(result.trace, "final_guardian")[0].status == "completed"


async def test_strict_mode_repair_is_bounded(tmp_path):
    storage = Storage(tmp_path / "strict-repair.db")
    character = CharacterCore(name="Strict")
    provider = ScriptedProvider(["AIとして回答します。", "一緒に歩こう。"])
    result = await ChatService(storage, default_quality_mode="strict").run(
        provider=provider,
        model="small",
        character=character,
        user_input="散歩しよう",
    )

    assert result.repaired
    assert len(provider.calls) == 2
    assert len(step(result.trace, "guardian")) == 2
    assert len(step(result.trace, "final_guardian")) == 1


async def test_quality_mode_precedence_is_conversation_character_global(setup_chat):
    storage, original_character, conversation_id = setup_chat
    service = ChatService(storage, default_quality_mode="fast")

    character = original_character.model_copy(update={"quality_mode": "strict"})
    storage.save_character(character)
    storage.set_conversation_quality_mode(conversation_id, "balanced")

    balanced = await service.run(
        provider=ScriptedProvider(["普通の返答。"]),
        model="small",
        character=character,
        conversation_id=conversation_id,
        user_input="こんにちは",
    )
    assert balanced.quality_mode == "balanced"

    inherited_conversation = storage.create_conversation(character.id)
    strict = await service.run(
        provider=ScriptedProvider(["普通の返答。"]),
        model="small",
        character=character,
        conversation_id=inherited_conversation,
        user_input="こんにちは",
    )
    assert strict.quality_mode == "strict"

    global_character = CharacterCore(name="Global")
    fast = await service.run(
        provider=ScriptedProvider(["普通の返答。"]),
        model="small",
        character=global_character,
        user_input="こんにちは",
    )
    assert fast.quality_mode == "fast"


async def test_trace_keeps_explicit_post_final_placeholders(tmp_path):
    storage = Storage(tmp_path / "trace.db")
    result = await ChatService(storage).run(
        provider=ScriptedProvider(["こんにちは。"]),
        model="small",
        character=CharacterCore(name="Trace"),
        user_input="こんにちは",
    )
    assert step(result.trace, "input_analysis")
    assert step(result.trace, "primary_recall")
    assert step(result.trace, "context_build")
    assert step(result.trace, "draft_generation")
    assert step(result.trace, "lightweight_check")
    assert step(result.trace, "finalize")
    assert step(result.trace, "memory_extraction")[0].status == "skipped"
    assert step(result.trace, "state_update")[0].status == "skipped"
    assert step(result.trace, "evaluation_log")


async def test_balanced_recall_probe_preserves_lexical_memory_matches(tmp_path):
    storage = Storage(tmp_path / "balanced-lexical.db")
    character = CharacterCore(name="Balanced")
    storage.upsert_memory(
        MemoryRecord(
            character_id=character.id,
            type="episodic",
            content="lighthouse promise stay away",
            importance=0.8,
        )
    )
    provider = ScriptedProvider(["visit lighthouse", "stay away from the lighthouse"])
    result = await ChatService(storage).run(
        provider=provider,
        model="small",
        character=character,
        user_input="take a walk",
    )

    assert result.regenerated_for_recall
    assert len(provider.calls) == 2
    analysis = step(result.trace, "draft_analysis")[0]
    assert "secondary_recall_probe" in analysis.details["inspect_signals"]


async def test_turn_trace_includes_structured_input_and_context_debug(tmp_path):
    storage = Storage(tmp_path / "trace-context.db")
    character = CharacterCore(
        name="ミカ",
        lore=["海辺の町"],
        relationship=["幼なじみ"],
    )
    provider = ScriptedProvider(["明日の東京駅の話、覚えておくね。"])
    result = await ChatService(storage).run(
        provider=provider,
        model="small",
        character=character,
        user_input="明日、東京駅の話を覚えておいて？",
    )

    analysis_step = step(result.trace, "input_analysis")[0]
    assert analysis_step.details["explicit_memory_request"] is True
    assert "明日" in analysis_step.details["time_references"]
    assert "東京駅" in analysis_step.details["places"]

    context_step = step(result.trace, "context_build")[0]
    debug = context_step.details["debug"]
    assert debug["order"] == [
        "runtime_rules",
        "character_core",
        "critical_lore",
        "relationship_state",
        "current_state",
        "relevant_memories",
        "recent_conversation",
        "user_message",
    ]
    assert debug["estimated_tokens"] <= debug["max_tokens"]
    assert debug["used_bytes"] <= debug["max_bytes"]
