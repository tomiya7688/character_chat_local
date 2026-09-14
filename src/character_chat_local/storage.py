from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .models import CharacterCore, ChatMessage, GuardianResult, MemoryRecord


class Storage:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS response_evaluations (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    original_response TEXT NOT NULL,
                    final_response TEXT NOT NULL,
                    guardian_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def save_character(self, character: CharacterCore) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO characters(id, data_json) VALUES (?, ?)",
                (character.id, character.model_dump_json()),
            )

    def load_character(self, character_id: str) -> CharacterCore | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT data_json FROM characters WHERE id = ?", (character_id,)
            ).fetchone()
        return CharacterCore.model_validate_json(row["data_json"]) if row else None

    def create_conversation(self, character_id: str) -> str:
        conversation_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversations(id, character_id) VALUES (?, ?)",
                (conversation_id, character_id),
            )
        return conversation_id

    def add_message(
        self,
        conversation_id: str,
        message: ChatMessage,
        provider: str | None = None,
        model: str | None = None,
    ) -> str:
        message_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (message_id, conversation_id, message.role, message.content, provider, model),
            )
        return message_id

    def list_messages(self, conversation_id: str) -> list[ChatMessage]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY rowid",
                (conversation_id,),
            ).fetchall()
        return [ChatMessage(role=row["role"], content=row["content"]) for row in rows]

    def upsert_memory(self, memory: MemoryRecord) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO memories(id, character_id, data_json) VALUES (?, ?, ?)",
                (memory.id, memory.character_id, memory.model_dump_json()),
            )

    def list_memories(self, character_id: str) -> list[MemoryRecord]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT data_json FROM memories WHERE character_id = ?", (character_id,)
            ).fetchall()
        return [MemoryRecord.model_validate_json(row["data_json"]) for row in rows]

    def save_evaluation(
        self,
        conversation_id: str | None,
        original_response: str,
        final_response: str,
        guardian: GuardianResult,
    ) -> str:
        evaluation_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO response_evaluations VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (
                    evaluation_id,
                    conversation_id,
                    original_response,
                    final_response,
                    json.dumps(guardian.model_dump(), ensure_ascii=False),
                ),
            )
        return evaluation_id
