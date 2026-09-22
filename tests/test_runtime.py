import asyncio
import json
import sqlite3

import httpx
import pytest
from conftest import ScriptedProvider

from character_chat_local.models import CharacterCore, ChatMessage, MemoryRecord
from character_chat_local.prompting import ContextBudgetError, build_messages, prompt_size
from character_chat_local.providers import ProviderError
from character_chat_local.recall import RecallEngine
from character_chat_local.service import ChatService, QualityRejected
from character_chat_local.storage import ConversationConflict, Storage


async def run_turn(setup_chat, provider, **kwargs):
    storage, character, conversation = setup_chat
    return await ChatService(storage).run(
        provider=provider, model="small", character=character,
        conversation_id=conversation, user_input="散歩しよう", **kwargs,
    )


async def test_repair_only_accepted_reply_is_in_history(setup_chat):
    storage, _, conversation = setup_chat
    provider = ScriptedProvider(["AIとして回答します。", "一緒に歩こう。"])
    result = await run_turn(setup_chat, provider)
    assert result.repaired and result.guardian.passed
    assert len(provider.calls) == provider.closed == 2
    assert [m.content for m in storage.list_messages(conversation)] == ["散歩しよう", "一緒に歩こう。"]
    assert "meta_leak" in provider.calls[1][1][0].content
    with storage.session() as db:
        row = db.execute("SELECT * FROM response_evaluations").fetchone()
        assert row["original_response"] == "AIとして回答します。"
        assert len(json.loads(row["metadata_json"])["attempts"]) == 2


@pytest.mark.parametrize("bad", ["AIとして回答します。", "", "ええ。ええ。ええ。"])
async def test_fail_closed_and_bounded_repair(setup_chat, bad):
    storage, _, conversation = setup_chat
    provider = ScriptedProvider([bad])
    with pytest.raises(QualityRejected):
        await run_turn(setup_chat, provider)
    assert len(provider.calls) == 2
    assert storage.list_messages(conversation) == []
    assert storage.get_conversation(conversation).revision == 0
    with storage.session() as db:
        assert db.execute("SELECT final_response FROM response_evaluations").fetchone()[0] == ""


async def test_secondary_then_repair_at_most_three_calls(setup_chat):
    storage, character, _ = setup_chat
    storage.upsert_memory(MemoryRecord(
        character_id=character.id, type="episodic", content="灯台へは行かない約束",
        triggers=["灯台"],
    ))
    provider = ScriptedProvider(["灯台へ行こう", "", "港を歩こう。"])
    result = await run_turn(setup_chat, provider)
    assert result.regenerated_for_recall and result.repaired
    assert len(provider.calls) == 3
    assert all(prompt_size(messages) <= 24000 for _, messages in provider.calls)


async def test_no_unnecessary_retry(setup_chat, provider):
    result = await run_turn(setup_chat, provider)
    assert not result.repaired and not result.regenerated_for_recall
    assert len(provider.calls) == 1


async def test_empty_first_reply_can_be_repaired(setup_chat):
    result = await run_turn(setup_chat, ScriptedProvider(["", "こんにちは。"]))
    assert result.repaired


async def test_http_failure_does_not_save_half_turn(setup_chat):
    storage, _, conversation = setup_chat
    with pytest.raises(ProviderError, match="provider request failed"):
        await run_turn(setup_chat, ScriptedProvider([httpx.ReadError("secret-canary")]))
    assert storage.list_messages(conversation) == []


async def test_output_bound_closes_stream(setup_chat):
    provider = ScriptedProvider(["a" * 8001])
    with pytest.raises(ProviderError, match="output limit"):
        await run_turn(setup_chat, provider)
    assert provider.closed == 1
    assert setup_chat[0].list_messages(setup_chat[2]) == []


async def test_timeout_and_cancellation_leave_no_messages(setup_chat):
    class Slow(ScriptedProvider):
        async def stream_chat(self, **kwargs):
            self.started.set()
            try:
                await asyncio.Event().wait()
                yield "unused"
            finally:
                self.closed += 1

    storage, character, conversation = setup_chat
    provider = Slow()
    provider.started = asyncio.Event()
    with pytest.raises(ProviderError, match="timed out"):
        await ChatService(storage, timeout=0.01).run(
            provider=provider, model="small", character=character,
            conversation_id=conversation, user_input="こんにちは",
        )
    provider.started = asyncio.Event()
    task = asyncio.create_task(run_turn(setup_chat, provider))
    await provider.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.closed == 2
    assert storage.list_messages(conversation) == []


async def test_persistent_history_is_server_owned(setup_chat, provider):
    with pytest.raises(ValueError, match="server-owned"):
        await run_turn(setup_chat, provider, history=[])
    assert not provider.calls


async def test_character_mismatch_is_rejected(setup_chat, provider):
    storage, _, conversation = setup_chat
    with pytest.raises(ValueError, match="does not match"):
        await ChatService(storage).run(
            provider=provider, model="small", character=CharacterCore(name="other"),
            conversation_id=conversation, user_input="hello",
        )
    assert not provider.calls


async def test_optimistic_revision_rejects_stale_turn(setup_chat):
    storage, _, conversation = setup_chat
    class Racing(ScriptedProvider):
        async def stream_chat(self, **kwargs):
            storage.add_message(conversation, ChatMessage(role="user", content="external edit"))
            yield "こんにちは。"
    with pytest.raises(ConversationConflict):
        await run_turn(setup_chat, Racing())
    assert [m.content for m in storage.list_messages(conversation)] == ["external edit"]


async def test_sql_failure_rolls_back_whole_turn(setup_chat, provider, monkeypatch):
    storage, _, conversation = setup_chat
    def fail(*args, **kwargs):
        raise sqlite3.IntegrityError("injected failure")
    monkeypatch.setattr(storage, "_evaluation", fail)
    with pytest.raises(sqlite3.IntegrityError):
        await run_turn(setup_chat, provider)
    assert storage.list_messages(conversation) == []
    assert storage.get_conversation(conversation).revision == 0
    with storage.session() as db:
        assert db.execute("SELECT count(*) FROM conversation_summaries").fetchone()[0] == 0


def test_storage_closes_connections(setup_chat):
    with setup_chat[0].session() as db:
        db.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")


def test_additive_legacy_schema_migration(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE conversations(id TEXT PRIMARY KEY, character_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE response_evaluations(id TEXT PRIMARY KEY, conversation_id TEXT,
                original_response TEXT NOT NULL, final_response TEXT NOT NULL,
                guardian_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO conversations(id, character_id) VALUES ('old', 'c');
            INSERT INTO response_evaluations VALUES ('e', 'old', 'draft', 'reply', '{"passed":true}', CURRENT_TIMESTAMP);
        """)
    storage = Storage(path)
    storage = Storage(path)
    assert storage.get_conversation("old").revision == 0
    with storage.session() as db:
        row = db.execute("SELECT * FROM response_evaluations").fetchone()
        assert row["final_response"] == "reply" and row["metadata_json"] == "{}"


def test_complete_character_core_and_bounded_japanese_context():
    character = CharacterCore(name="ミカ", first_person="私", speech_style=["穏やか"], lore=["海辺"], forbidden=["禁止語"])
    history = [ChatMessage(role=role, content="古い話" * 500) for _ in range(30) for role in ("user", "assistant")]
    result = build_messages(character=character, history=history, user_input="今の質問", recalled=[], max_prompt_bytes=4000)
    assert prompt_size(result) <= 4000
    assert all(value in result[0].content for value in ["ミカ", "私", "穏やか", "海辺", "禁止語"])
    assert result[-1].content == "今の質問"
    assert result[1].role == "user"
    with pytest.raises(ContextBudgetError):
        build_messages(character=character, history=[], user_input="x", recalled=[], max_prompt_bytes=10)


def test_recall_never_admits_oversized_first_item_or_empty_trigger():
    big = MemoryRecord(character_id="c", type="episodic", content="猫" * 100, triggers=["猫"])
    unrelated = MemoryRecord(character_id="c", type="canon", content="雨", triggers=[""], activation_threshold=0)
    assert not RecallEngine().recall("猫", [big], token_budget=10).hits
    assert not RecallEngine().recall("猫", [unrelated]).hits
    assert not RecallEngine().recall("猫", [big], token_budget=0).hits
