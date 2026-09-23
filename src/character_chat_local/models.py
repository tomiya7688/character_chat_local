from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


Role = Literal["system", "user", "assistant"]
MemoryType = Literal[
    "canon",
    "relationship",
    "episodic",
    "user_fact",
    "inferred_fact",
    "current_state",
]
RecallMode = Literal["explicit", "implicit", "behavioral", "emotional", "internal_only"]


class ChatMessage(BaseModel):
    role: Role
    content: str


class ModelInfo(BaseModel):
    id: str
    provider: str
    display_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CharacterCore(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=200)
    first_person: str | None = None
    second_person: str | None = None
    speech_style: list[str] = Field(default_factory=list)
    personality: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    background: list[str] = Field(default_factory=list)
    lore: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    relationship: list[str] = Field(default_factory=list)
    response_style: list[str] = Field(default_factory=list)


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    character_id: str
    type: MemoryType
    content: str
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    triggers: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)
    recall_mode: RecallMode = "implicit"
    activation_threshold: float = Field(default=0.2, ge=0, le=1)
    source_message_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RecallHit(BaseModel):
    memory: MemoryRecord
    score: float
    reasons: list[str] = Field(default_factory=list)


class RecallBundle(BaseModel):
    hits: list[RecallHit] = Field(default_factory=list)
    approx_tokens: int = 0


GuardianCategory = Literal[
    "character_break",
    "lore_violation",
    "memory_violation",
    "user_control",
    "repetition",
    "meta_leak",
    "formatting_break",
]


class GuardianFinding(BaseModel):
    category: GuardianCategory
    severity: float = Field(ge=0, le=1)
    reason: str


class GuardianResult(BaseModel):
    passed: bool
    findings: list[GuardianFinding] = Field(default_factory=list)


class ChatRunResult(BaseModel):
    text: str
    draft: str
    primary_recall: RecallBundle
    secondary_recall: RecallBundle
    guardian: GuardianResult
    regenerated_for_recall: bool = False
    repaired: bool = False


class StoredMessage(ChatMessage):
    id: str
    position: int
    provider: str | None = None
    model: str | None = None


class ConversationInfo(BaseModel):
    id: str
    character_id: str
    revision: int = 0


class SummaryEntry(BaseModel):
    source_message_id: str
    position: int
    role: Role
    excerpt: str
    priority: int = 0


class ConversationSummary(BaseModel):
    strategy: Literal["extractive-v1"] = "extractive-v1"
    through_position: int = 0
    covered_messages: int = 0
    entries: list[SummaryEntry] = Field(default_factory=list)
