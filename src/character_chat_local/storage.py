from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import (
    CharacterCore,
    ChatMessage,
    ConversationInfo,
    ConversationSummary,
    GuardianResult,
    MemoryRecord,
    StoredMessage,
)


class ConversationConflict(RuntimeError):
    pass


class Storage:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError(
                "use a temporary file; connections are scoped per operation"
            )
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        db = self.connect()
        try:
            with db:
                yield db
        finally:
            # sqlite3.Connection.__exit__ commits/rolls back but does not close.
            db.close()

    def initialize(self) -> None:
        with self.session() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY, data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, character_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, provider TEXT, model TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, character_id TEXT NOT NULL, data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS response_evaluations (
                    id TEXT PRIMARY KEY, conversation_id TEXT,
                    original_response TEXT NOT NULL, final_response TEXT NOT NULL,
                    guardian_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    conversation_id TEXT PRIMARY KEY, data_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_messages_conversation
                    ON messages(conversation_id);
                CREATE INDEX IF NOT EXISTS ix_memories_character
                    ON memories(character_id);
            """)
            # Additive migration: preserve existing DBs, message IDs and row order.
            if "revision" not in {
                r["name"] for r in db.execute("PRAGMA table_info(conversations)")
            }:
                db.execute(
                    "ALTER TABLE conversations ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )
            if "metadata_json" not in {
                r["name"] for r in db.execute("PRAGMA table_info(response_evaluations)")
            }:
                db.execute(
                    "ALTER TABLE response_evaluations ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )

    def save_character(self, character: CharacterCore) -> None:
        with self.session() as db:
            db.execute(
                "INSERT INTO characters(id, data_json) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json",
                (character.id, character.model_dump_json()),
            )

    def load_character(self, character_id: str) -> CharacterCore | None:
        with self.session() as db:
            row = db.execute(
                "SELECT data_json FROM characters WHERE id=?", (character_id,)
            ).fetchone()
        return CharacterCore.model_validate_json(row["data_json"]) if row else None

    def list_characters(self, limit: int = 100) -> list[CharacterCore]:
        with self.session() as db:
            rows = db.execute(
                "SELECT data_json FROM characters ORDER BY rowid LIMIT ?", (limit,)
            ).fetchall()
        return [CharacterCore.model_validate_json(r["data_json"]) for r in rows]

    def create_conversation(self, character_id: str) -> str:
        conversation_id = str(uuid4())
        with self.session() as db:
            if not db.execute(
                "SELECT 1 FROM characters WHERE id=?", (character_id,)
            ).fetchone():
                raise KeyError("character not found")
            db.execute(
                "INSERT INTO conversations(id, character_id) VALUES (?, ?)",
                (conversation_id, character_id),
            )
        return conversation_id

    @staticmethod
    def _conversation(db: sqlite3.Connection, conversation_id: str) -> ConversationInfo:
        row = db.execute(
            "SELECT id, character_id, revision FROM conversations WHERE id=?",
            (conversation_id,),
        ).fetchone()
        if not row:
            raise KeyError("conversation not found")
        return ConversationInfo.model_validate(dict(row))

    def get_conversation(self, conversation_id: str) -> ConversationInfo:
        with self.session() as db:
            return self._conversation(db, conversation_id)

    def list_conversations(self, limit: int = 100) -> list[ConversationInfo]:
        with self.session() as db:
            rows = db.execute(
                "SELECT id, character_id, revision FROM conversations ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [ConversationInfo.model_validate(dict(row)) for row in rows]

    @staticmethod
    def _summary(db: sqlite3.Connection, conversation_id: str) -> ConversationSummary:
        row = db.execute(
            "SELECT data_json FROM conversation_summaries WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        return (
            ConversationSummary.model_validate_json(row["data_json"])
            if row
            else ConversationSummary()
        )

    def get_summary(self, conversation_id: str) -> ConversationSummary:
        with self.session() as db:
            self._conversation(db, conversation_id)
            return self._summary(db, conversation_id)

    @contextmanager
    def context_snapshot(
        self, conversation_id: str
    ) -> Iterator[
        tuple[ConversationInfo, ConversationSummary, Iterator[StoredMessage]]
    ]:
        with self.session() as db:
            db.execute("BEGIN")
            conversation = self._conversation(db, conversation_id)
            summary = self._summary(db, conversation_id)
            rows = db.execute(
                "SELECT rowid AS position, id, role, content, provider, model "
                "FROM messages WHERE conversation_id=? AND rowid>? ORDER BY rowid",
                (conversation_id, summary.through_position),
            )
            yield (
                conversation,
                summary,
                (StoredMessage.model_validate(dict(r)) for r in rows),
            )

    @staticmethod
    def _insert_message(
        db: sqlite3.Connection,
        conversation_id: str,
        message: ChatMessage,
        provider: str | None = None,
        model: str | None = None,
    ) -> str:
        message_id = str(uuid4())
        db.execute(
            "INSERT INTO messages(id, conversation_id, role, content, provider, model) VALUES (?, ?, ?, ?, ?, ?)",
            (
                message_id,
                conversation_id,
                message.role,
                message.content,
                provider,
                model,
            ),
        )
        return message_id

    def add_message(
        self,
        conversation_id: str,
        message: ChatMessage,
        provider: str | None = None,
        model: str | None = None,
    ) -> str:
        with self.session() as db:
            self._conversation(db, conversation_id)
            result = self._insert_message(db, conversation_id, message, provider, model)
            db.execute(
                "UPDATE conversations SET revision=revision+1 WHERE id=?",
                (conversation_id,),
            )
        return result

    def list_messages(self, conversation_id: str) -> list[ChatMessage]:
        with self.session() as db:
            rows = db.execute(
                "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY rowid",
                (conversation_id,),
            ).fetchall()
        return [ChatMessage(role=r["role"], content=r["content"]) for r in rows]

    def list_message_records(
        self, conversation_id: str, *, after: int = 0, limit: int = 100
    ) -> list[StoredMessage]:
        with self.session() as db:
            self._conversation(db, conversation_id)
            rows = db.execute(
                "SELECT rowid AS position, id, role, content, provider, model FROM messages "
                "WHERE conversation_id=? AND rowid>? ORDER BY rowid LIMIT ?",
                (conversation_id, after, limit),
            ).fetchall()
        return [StoredMessage.model_validate(dict(r)) for r in rows]

    def upsert_memory(self, memory: MemoryRecord) -> None:
        with self.session() as db:
            existing = db.execute(
                "SELECT character_id FROM memories WHERE id=?", (memory.id,)
            ).fetchone()
            if existing and existing["character_id"] != memory.character_id:
                raise ValueError("memory belongs to another character")
            if memory.source_message_id:
                source = db.execute(
                    "SELECT c.character_id FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=?",
                    (memory.source_message_id,),
                ).fetchone()
                if not source or source["character_id"] != memory.character_id:
                    raise ValueError("memory source must belong to the same character")
            db.execute(
                "INSERT INTO memories(id, character_id, data_json) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json",
                (memory.id, memory.character_id, memory.model_dump_json()),
            )

    def list_memories(self, character_id: str) -> list[MemoryRecord]:
        with self.session() as db:
            rows = db.execute(
                "SELECT data_json FROM memories WHERE character_id=? ORDER BY rowid",
                (character_id,),
            ).fetchall()
        return [MemoryRecord.model_validate_json(r["data_json"]) for r in rows]

    @staticmethod
    def _evaluation(
        db: sqlite3.Connection,
        conversation_id: str | None,
        original_response: str,
        final_response: str,
        guardian: GuardianResult,
        metadata: dict[str, Any] | None,
    ) -> str:
        evaluation_id = str(uuid4())
        db.execute(
            "INSERT INTO response_evaluations(id, conversation_id, original_response, final_response, guardian_json, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                evaluation_id,
                conversation_id,
                original_response,
                final_response,
                guardian.model_dump_json(),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        return evaluation_id

    def save_evaluation(
        self,
        conversation_id: str | None,
        original_response: str,
        final_response: str,
        guardian: GuardianResult,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        with self.session() as db:
            return self._evaluation(
                db,
                conversation_id,
                original_response,
                final_response,
                guardian,
                metadata,
            )

    def commit_turn(
        self,
        *,
        conversation: ConversationInfo,
        user_input: str,
        text: str,
        provider: str,
        model: str,
        summary: ConversationSummary,
        draft: str,
        guardian: GuardianResult,
        metadata: dict[str, Any],
    ) -> None:
        if not guardian.passed or not text.strip():
            raise ValueError("only accepted non-empty replies may be committed")
        with self.session() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._conversation(db, conversation.id)
            if current.revision != conversation.revision:
                raise ConversationConflict(
                    "conversation changed during generation; retry"
                )
            self._insert_message(
                db, conversation.id, ChatMessage(role="user", content=user_input)
            )
            self._insert_message(
                db,
                conversation.id,
                ChatMessage(role="assistant", content=text),
                provider,
                model,
            )
            db.execute(
                "INSERT INTO conversation_summaries(conversation_id, data_json) VALUES (?, ?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET data_json=excluded.data_json",
                (conversation.id, summary.model_dump_json()),
            )
            self._evaluation(db, conversation.id, draft, text, guardian, metadata)
            db.execute(
                "UPDATE conversations SET revision=revision+1 WHERE id=?",
                (conversation.id,),
            )
