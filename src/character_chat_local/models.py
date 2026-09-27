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
GenerationStatus = Literal["generating", "completed", "stopped", "failed", "superseded"]
QualityMode = Literal["fast", "balanced", "strict"]
TurnStepStatus = Literal["completed", "skipped", "failed"]
EpistemicState = Literal["confirmed", "inferred", "hypothesis"]
KnowledgeSourceRole = Literal["user", "assistant"]
KnowledgeOwnerType = Literal["world", "user", "character"]
KnowledgeRecordType = Literal[
    "FACT",
    "CLAIM",
    "INTENT",
    "PLAN",
    "INFERENCE",
    "HYPOTHESIS",
    "PREDICTION",
    "EVENT",
]
KnowledgeStatus = Literal["active", "superseded", "invalidated"]
TemporalContext = Literal[
    "past",
    "present",
    "future",
    "flashback",
    "planned",
    "unknown",
]
TaskRole = Literal[
    "main_chat",
    "knowledge_extractor",
    "draft_analyzer",
    "knowledge_orchestrator",
    "guardian",
    "repair",
]
ContextSectionName = Literal[
    "runtime_rules",
    "character_core",
    "critical_lore",
    "relationship_state",
    "current_state",
    "relevant_memories",
    "recent_conversation",
    "user_message",
]


class ChatMessage(BaseModel):
    role: Role
    content: str


class TaskAssignment(BaseModel):
    provider_id: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.1, ge=0, le=2)


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
    quality_mode: QualityMode | None = None


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


class InputAnalysisResult(BaseModel):
    strategy: Literal["heuristic-v2"] = "heuristic-v2"
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    emotions: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    time_references: list[str] = Field(default_factory=list)
    explicit_memory_request: bool = False


class ContextSectionDebug(BaseModel):
    name: ContextSectionName
    budget_tokens: int
    used_tokens: int = 0
    selected_items: int = 0
    dropped_items: int = 0
    labels: list[str] = Field(default_factory=list)


class ContextDebug(BaseModel):
    order: list[ContextSectionName]
    max_tokens: int
    estimated_tokens: int
    max_bytes: int
    used_bytes: int
    sections: list[ContextSectionDebug] = Field(default_factory=list)


class ContextBuildResult(BaseModel):
    messages: list[ChatMessage]
    debug: ContextDebug


class EntityCandidate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_role: KnowledgeSourceRole
    epistemic_state: EpistemicState
    confidence: float = Field(ge=0, le=1)


class FactCandidate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=500)
    source_role: KnowledgeSourceRole
    epistemic_state: EpistemicState
    confidence: float = Field(ge=0, le=1)


class RelationCandidate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=120)
    object: str = Field(min_length=1, max_length=200)
    source_role: KnowledgeSourceRole
    epistemic_state: EpistemicState
    confidence: float = Field(ge=0, le=1)


class EventCandidate(BaseModel):
    description: str = Field(min_length=1, max_length=800)
    time_reference: str | None = Field(default=None, max_length=120)
    entities: list[str] = Field(default_factory=list)
    source_role: KnowledgeSourceRole
    epistemic_state: EpistemicState
    confidence: float = Field(ge=0, le=1)


class PreferenceCandidate(BaseModel):
    subject: str = Field(default="user", min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=300)
    sentiment: Literal["like", "dislike"]
    source_role: KnowledgeSourceRole
    epistemic_state: EpistemicState
    confidence: float = Field(ge=0, le=1)


class AliasCandidate(BaseModel):
    entity: str = Field(min_length=1, max_length=200)
    alias: str = Field(min_length=1, max_length=200)
    source_role: KnowledgeSourceRole
    epistemic_state: EpistemicState
    confidence: float = Field(ge=0, le=1)


class DynamicStateCandidate(BaseModel):
    owner: Literal["user", "character"]
    key: Literal["emotion", "location", "concern", "unresolved_event", "recent_event"]
    value: str = Field(min_length=1, max_length=500)
    source_role: KnowledgeSourceRole
    epistemic_state: EpistemicState
    confidence: float = Field(ge=0, le=1)


class RelationshipCandidate(BaseModel):
    dimension: Literal["relationship", "trust", "affection"]
    label: str = Field(min_length=1, max_length=300)
    delta: float = Field(default=0.0, ge=-1, le=1)
    source_role: KnowledgeSourceRole
    epistemic_state: EpistemicState
    confidence: float = Field(ge=0, le=1)


class KnowledgeExtractionResult(BaseModel):
    strategy: Literal["deterministic-v1", "model-v1", "model-fallback-v1"]
    entities: list[EntityCandidate] = Field(default_factory=list)
    facts: list[FactCandidate] = Field(default_factory=list)
    relations: list[RelationCandidate] = Field(default_factory=list)
    events: list[EventCandidate] = Field(default_factory=list)
    preferences: list[PreferenceCandidate] = Field(default_factory=list)
    aliases: list[AliasCandidate] = Field(default_factory=list)
    current_state_candidates: list[DynamicStateCandidate] = Field(default_factory=list)
    relationship_candidates: list[RelationshipCandidate] = Field(default_factory=list)
    fallback_reason: str | None = None


class TurnCommitResult(BaseModel):
    user_message_id: str
    assistant_message_id: str
    evaluation_id: str


class KnowledgeExtractionRecord(BaseModel):
    id: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    extraction: KnowledgeExtractionResult
    created_at: datetime


class DynamicStateRecord(BaseModel):
    id: str
    character_id: str
    owner: Literal["user", "character"]
    key: Literal["emotion", "location", "concern", "unresolved_event", "recent_event"]
    value: str
    confidence: float = Field(ge=0, le=1)
    epistemic_state: EpistemicState
    source_message_id: str
    created_at: datetime


class RelationshipStateRecord(BaseModel):
    id: str
    change_id: str
    character_id: str
    dimension: Literal["relationship", "trust", "affection"]
    score: float = Field(ge=-1, le=1)
    label: str
    confidence: float = Field(ge=0, le=1)
    epistemic_state: EpistemicState
    source_message_id: str
    created_at: datetime


class StateCommitResult(BaseModel):
    dynamic_states: list[DynamicStateRecord] = Field(default_factory=list)
    relationship_states: list[RelationshipStateRecord] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)


class KnowledgeOwnerRecord(BaseModel):
    id: str
    owner_type: KnowledgeOwnerType
    character_id: str | None = None
    timeline_id: str = "main"
    temporal_instance: str = "present"
    created_at: datetime


class KnowledgeEntityRecord(BaseModel):
    id: str
    owner_id: str
    canonical_name: str
    normalized_name: str
    entity_type: str = "unknown"
    base_character_id: str | None = None
    timeline_id: str = "main"
    temporal_instance: str = "present"
    created_at: datetime


class KnowledgeAliasRecord(BaseModel):
    id: str
    owner_id: str
    entity_id: str
    alias: str
    normalized_alias: str
    source_message_id: str | None = None
    created_at: datetime


class KnowledgeRecord(BaseModel):
    id: str
    owner_id: str
    subject_entity_id: str
    predicate: str
    value: str
    record_type: KnowledgeRecordType
    status: KnowledgeStatus
    confidence: float = Field(ge=0, le=1)
    epistemic_state: EpistemicState
    source_role: KnowledgeSourceRole
    timeline_id: str = "main"
    temporal_context: TemporalContext = "unknown"
    scene_id: str | None = None
    arc_id: str | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    known_from: datetime | None = None
    known_until: datetime | None = None
    superseded_by: str | None = None
    invalidated_at: datetime | None = None
    conversation_id: str
    branch_id: str
    created_at: datetime
    updated_at: datetime


class KnowledgeRelationRecord(BaseModel):
    id: str
    owner_id: str
    subject_entity_id: str
    relation_type: str
    object_entity_id: str
    inverse_relation_type: str | None = None
    symmetric: bool = False
    status: KnowledgeStatus
    confidence: float = Field(ge=0, le=1)
    epistemic_state: EpistemicState
    source_role: KnowledgeSourceRole
    timeline_id: str = "main"
    temporal_context: TemporalContext = "unknown"
    conversation_id: str
    branch_id: str
    created_at: datetime
    updated_at: datetime


class KnowledgeProvenanceRecord(BaseModel):
    id: str
    knowledge_kind: Literal["entity", "alias", "record", "relation"]
    knowledge_id: str
    source_message_id: str
    source_role: KnowledgeSourceRole
    conversation_id: str
    branch_id: str
    created_at: datetime


class KnowledgeRelationLookupHit(BaseModel):
    relation_id: str
    direction: Literal["forward", "reverse"]
    subject: str
    relation_type: str
    effective_relation_type: str
    object: str
    confidence: float = Field(ge=0, le=1)


class KnowledgeRecordLookupHit(BaseModel):
    record: KnowledgeRecord
    subject: str
    matched_on: Literal["subject", "value"]


class KnowledgePromotionResult(BaseModel):
    owner_id: str
    entities_created: int = 0
    aliases_created: int = 0
    records_created: int = 0
    records_merged: int = 0
    records_superseded: int = 0
    relations_created: int = 0
    relations_merged: int = 0
    rejected: list[str] = Field(default_factory=list)


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


class LightweightCheckResult(BaseModel):
    passed: bool
    requires_inspection: bool = False
    findings: list[GuardianFinding] = Field(default_factory=list)
    inspect_signals: list[str] = Field(default_factory=list)


class TurnStepResult(BaseModel):
    name: str
    status: TurnStepStatus = "completed"
    details: dict[str, Any] = Field(default_factory=dict)


class TurnTrace(BaseModel):
    quality_mode: QualityMode
    steps: list[TurnStepResult] = Field(default_factory=list)


class ChatRunResult(BaseModel):
    text: str
    draft: str
    primary_recall: RecallBundle
    secondary_recall: RecallBundle
    guardian: GuardianResult
    quality_mode: QualityMode = "balanced"
    trace: TurnTrace
    regenerated_for_recall: bool = False
    repaired: bool = False


class StoredMessage(ChatMessage):
    id: str
    position: int
    provider: str | None = None
    model: str | None = None
    generation_id: str | None = None
    origin_message_id: str | None = None


class ConversationInfo(BaseModel):
    id: str
    character_id: str
    revision: int = 0
    parent_conversation_id: str | None = None
    forked_from_message_id: str | None = None
    supersedes_message_id: str | None = None
    fork_reason: Literal["regenerate", "edit_retry"] | None = None
    pending: bool = False
    quality_mode: QualityMode | None = None


class GenerationRun(BaseModel):
    id: str
    conversation_id: str
    status: GenerationStatus
    provider: str
    model: str
    error_code: str | None = None
    superseded_by_generation_id: str | None = None
    created_at: datetime
    updated_at: datetime


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
