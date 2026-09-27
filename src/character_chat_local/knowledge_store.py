from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from uuid import uuid4

from .models import (
    EpistemicState,
    KnowledgeAliasRecord,
    KnowledgeEntityRecord,
    KnowledgeExtractionResult,
    KnowledgeOwnerRecord,
    KnowledgeOwnerType,
    KnowledgePromotionResult,
    KnowledgeProvenanceRecord,
    KnowledgeRecord,
    KnowledgeRecordLookupHit,
    KnowledgeRecordType,
    KnowledgeRelationLookupHit,
    KnowledgeRelationRecord,
    KnowledgeSourceRole,
    TemporalContext,
)
from .storage import Storage

_RELATION_MAP: dict[str, tuple[str, str | None, bool]] = {
    "likes": ("likes", "liked_by", False),
    "liked_by": ("liked_by", "likes", False),
    "parent_of": ("parent_of", "child_of", False),
    "child_of": ("child_of", "parent_of", False),
    "located_in": ("located_in", "contains", False),
    "contains": ("contains", "located_in", False),
    "has_property": ("has_property", "property_of", False),
    "property_of": ("property_of", "has_property", False),
    "friend_of": ("friend_of", "friend_of", True),
    "close_friend_of": ("close_friend_of", "close_friend_of", True),
    "partner_of": ("partner_of", "partner_of", True),
    "友達": ("friend_of", "friend_of", True),
    "親友": ("close_friend_of", "close_friend_of", True),
    "恋人": ("partner_of", "partner_of", True),
}
_SINGLE_VALUE_PREDICATES = {
    "name",
    "age",
    "location",
    "current_location",
    "job",
    "occupation",
    "status",
    "relationship_status",
    "hair_color",
    "eye_color",
    "favorite_color",
}
_FUTURE_MARKERS = (
    "明日",
    "明後日",
    "来週",
    "来月",
    "来年",
    "予定",
    "つもり",
    "tomorrow",
    "next week",
    "next month",
    "next year",
    "going to",
    " will ",
)
_INTENT_MARKERS = (
    "したい",
    "しようと",
    "したがって",
    "する気",
    "want to",
    "intend to",
    "trying to",
)
_PREDICTION_MARKERS = (
    "だろう",
    "でしょう",
    "予想",
    "かもしれない",
    "probably",
    "likely",
    "might",
)
_PAST_MARKERS = ("昨日", "昔", "以前", "先週", "去年", "yesterday", "last week")
_FLASHBACK_MARKERS = ("回想", "当時", "flashback")
_SPACE_RE = re.compile(r"\s+")


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_knowledge_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _SPACE_RE.sub(" ", normalized).strip(" 、。！？!?.,:;\"'()[]{}")


def _temporal_context(text: str, time_reference: str | None = None) -> TemporalContext:
    combined = f"{time_reference or ''} {text}".casefold()
    if any(marker.casefold() in combined for marker in _FLASHBACK_MARKERS):
        return "flashback"
    if any(marker.casefold() in combined for marker in _FUTURE_MARKERS):
        return "planned"
    if any(marker.casefold() in combined for marker in _PAST_MARKERS):
        return "past"
    if time_reference:
        return "present"
    return "unknown"


def _record_type(
    *,
    source_role: KnowledgeSourceRole,
    epistemic_state: EpistemicState,
    text: str,
    event: bool = False,
    time_reference: str | None = None,
) -> KnowledgeRecordType:
    folded = text.casefold()
    if any(marker.casefold() in folded for marker in _INTENT_MARKERS):
        return "INTENT"
    if any(marker.casefold() in folded for marker in _FUTURE_MARKERS) or (
        time_reference
        and any(
            marker.casefold() in time_reference.casefold()
            for marker in _FUTURE_MARKERS
        )
    ):
        return "PLAN"
    if any(marker.casefold() in folded for marker in _PREDICTION_MARKERS):
        return "PREDICTION"
    if epistemic_state == "hypothesis":
        return "HYPOTHESIS"
    if epistemic_state == "inferred":
        return "INFERENCE"
    if source_role == "assistant":
        return "CLAIM"
    return "EVENT" if event else "FACT"


def _relation_mapping(predicate: str) -> tuple[str, str | None, bool]:
    direct = _RELATION_MAP.get(predicate)
    if direct:
        return direct
    normalized = normalize_knowledge_text(predicate).replace(" ", "_")
    return normalized or "related_to", None, False


class KnowledgeDictionary:
    """Additive canonical Knowledge layer; legacy Memory remains authoritative for Recall."""

    def __init__(self, storage: Storage):
        self.storage = storage
        self.initialize()

    def initialize(self) -> None:
        with self.storage.session() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_owners (
                    id TEXT PRIMARY KEY,
                    owner_type TEXT NOT NULL,
                    character_id TEXT NOT NULL DEFAULT '',
                    timeline_id TEXT NOT NULL DEFAULT 'main',
                    temporal_instance TEXT NOT NULL DEFAULT 'present',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_type, character_id, timeline_id, temporal_instance)
                );
                CREATE TABLE IF NOT EXISTS knowledge_entities (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'unknown',
                    base_character_id TEXT NOT NULL DEFAULT '',
                    timeline_id TEXT NOT NULL DEFAULT 'main',
                    temporal_instance TEXT NOT NULL DEFAULT 'present',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_id, normalized_name, timeline_id, temporal_instance)
                );
                CREATE TABLE IF NOT EXISTS knowledge_aliases (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    source_message_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner_id, normalized_alias)
                );
                CREATE TABLE IF NOT EXISTS knowledge_records (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    subject_entity_id TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    predicate_normalized TEXT NOT NULL,
                    value TEXT NOT NULL,
                    value_normalized TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence REAL NOT NULL,
                    epistemic_state TEXT NOT NULL,
                    source_role TEXT NOT NULL,
                    timeline_id TEXT NOT NULL DEFAULT 'main',
                    temporal_context TEXT NOT NULL DEFAULT 'unknown',
                    scene_id TEXT,
                    arc_id TEXT,
                    observed_at TEXT,
                    valid_from TEXT,
                    valid_to TEXT,
                    known_from TEXT,
                    known_until TEXT,
                    superseded_by TEXT,
                    invalidated_at TEXT,
                    conversation_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS knowledge_relations (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    subject_entity_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    object_entity_id TEXT NOT NULL,
                    inverse_relation_type TEXT,
                    symmetric INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence REAL NOT NULL,
                    epistemic_state TEXT NOT NULL,
                    source_role TEXT NOT NULL,
                    timeline_id TEXT NOT NULL DEFAULT 'main',
                    temporal_context TEXT NOT NULL DEFAULT 'unknown',
                    conversation_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS knowledge_provenance (
                    id TEXT PRIMARY KEY,
                    knowledge_kind TEXT NOT NULL,
                    knowledge_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    source_role TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(knowledge_kind, knowledge_id, source_message_id)
                );
                CREATE INDEX IF NOT EXISTS ix_knowledge_owner_identity
                    ON knowledge_owners(owner_type, character_id, timeline_id);
                CREATE INDEX IF NOT EXISTS ix_knowledge_entity_name
                    ON knowledge_entities(owner_id, normalized_name);
                CREATE INDEX IF NOT EXISTS ix_knowledge_alias_name
                    ON knowledge_aliases(owner_id, normalized_alias);
                CREATE INDEX IF NOT EXISTS ix_knowledge_record_subject
                    ON knowledge_records(
                        owner_id, subject_entity_id, predicate_normalized, status
                    );
                CREATE INDEX IF NOT EXISTS ix_knowledge_record_value
                    ON knowledge_records(owner_id, value_normalized, status);
                CREATE INDEX IF NOT EXISTS ix_knowledge_relation_forward
                    ON knowledge_relations(
                        owner_id, subject_entity_id, relation_type, status
                    );
                CREATE INDEX IF NOT EXISTS ix_knowledge_relation_reverse
                    ON knowledge_relations(
                        owner_id, object_entity_id, relation_type, status
                    );
                CREATE INDEX IF NOT EXISTS ix_knowledge_provenance_source
                    ON knowledge_provenance(source_message_id);
                """
            )

    def find_owner(
        self,
        owner_type: KnowledgeOwnerType,
        *,
        character_id: str | None = None,
        timeline_id: str = "main",
        temporal_instance: str = "present",
    ) -> KnowledgeOwnerRecord | None:
        stored_character_id = character_id or ""
        with self.storage.session() as db:
            row = db.execute(
                "SELECT * FROM knowledge_owners WHERE owner_type=? AND character_id=? "
                "AND timeline_id=? AND temporal_instance=?",
                (owner_type, stored_character_id, timeline_id, temporal_instance),
            ).fetchone()
        if row is None:
            return None
        return KnowledgeOwnerRecord(
            id=row["id"],
            owner_type=row["owner_type"],
            character_id=row["character_id"] or None,
            timeline_id=row["timeline_id"],
            temporal_instance=row["temporal_instance"],
            created_at=row["created_at"],
        )

    def get_or_create_owner(
        self,
        owner_type: KnowledgeOwnerType,
        *,
        character_id: str | None = None,
        timeline_id: str = "main",
        temporal_instance: str = "present",
    ) -> KnowledgeOwnerRecord:
        stored_character_id = character_id or ""
        with self.storage.session() as db:
            row = db.execute(
                "SELECT * FROM knowledge_owners WHERE owner_type=? AND character_id=? "
                "AND timeline_id=? AND temporal_instance=?",
                (owner_type, stored_character_id, timeline_id, temporal_instance),
            ).fetchone()
            if row is None:
                owner_id = str(uuid4())
                db.execute(
                    "INSERT INTO knowledge_owners("
                    "id, owner_type, character_id, timeline_id, temporal_instance"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (
                        owner_id,
                        owner_type,
                        stored_character_id,
                        timeline_id,
                        temporal_instance,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM knowledge_owners WHERE id=?", (owner_id,)
                ).fetchone()
        return KnowledgeOwnerRecord(
            id=row["id"],
            owner_type=row["owner_type"],
            character_id=row["character_id"] or None,
            timeline_id=row["timeline_id"],
            temporal_instance=row["temporal_instance"],
            created_at=row["created_at"],
        )

    def _owner(self, owner_id: str) -> KnowledgeOwnerRecord:
        with self.storage.session() as db:
            row = db.execute(
                "SELECT * FROM knowledge_owners WHERE id=?", (owner_id,)
            ).fetchone()
        if row is None:
            raise KeyError("knowledge owner not found")
        return KnowledgeOwnerRecord(
            id=row["id"],
            owner_type=row["owner_type"],
            character_id=row["character_id"] or None,
            timeline_id=row["timeline_id"],
            temporal_instance=row["temporal_instance"],
            created_at=row["created_at"],
        )

    def _entity_row(self, row) -> KnowledgeEntityRecord:
        return KnowledgeEntityRecord(
            id=row["id"],
            owner_id=row["owner_id"],
            canonical_name=row["canonical_name"],
            normalized_name=row["normalized_name"],
            entity_type=row["entity_type"],
            base_character_id=row["base_character_id"] or None,
            timeline_id=row["timeline_id"],
            temporal_instance=row["temporal_instance"],
            created_at=row["created_at"],
        )

    def resolve_entity(
        self,
        owner_id: str,
        name: str,
        *,
        entity_type: str = "unknown",
        base_character_id: str | None = None,
        source_message_id: str | None = None,
        source_role: KnowledgeSourceRole = "user",
        conversation_id: str = "",
        branch_id: str = "",
    ) -> tuple[KnowledgeEntityRecord, bool]:
        owner = self._owner(owner_id)
        normalized = normalize_knowledge_text(name)
        if not normalized:
            raise ValueError("entity name must not be blank")
        created = False
        with self.storage.session() as db:
            alias = db.execute(
                "SELECT e.* FROM knowledge_aliases a "
                "JOIN knowledge_entities e ON e.id=a.entity_id "
                "WHERE a.owner_id=? AND a.normalized_alias=?",
                (owner_id, normalized),
            ).fetchone()
            row = alias or db.execute(
                "SELECT * FROM knowledge_entities WHERE owner_id=? "
                "AND normalized_name=? AND timeline_id=? AND temporal_instance=?",
                (
                    owner_id,
                    normalized,
                    owner.timeline_id,
                    owner.temporal_instance,
                ),
            ).fetchone()
            if row is None:
                entity_id = str(uuid4())
                db.execute(
                    "INSERT INTO knowledge_entities("
                    "id, owner_id, canonical_name, normalized_name, entity_type, "
                    "base_character_id, timeline_id, temporal_instance"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entity_id,
                        owner_id,
                        name.strip(),
                        normalized,
                        entity_type,
                        base_character_id or "",
                        owner.timeline_id,
                        owner.temporal_instance,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM knowledge_entities WHERE id=?", (entity_id,)
                ).fetchone()
                created = True
        entity = self._entity_row(row)
        if source_message_id:
            self._add_provenance(
                "entity",
                entity.id,
                source_message_id,
                source_role,
                conversation_id,
                branch_id,
            )
        return entity, created

    def add_alias(
        self,
        owner_id: str,
        entity_id: str,
        alias: str,
        *,
        source_message_id: str | None,
        source_role: KnowledgeSourceRole,
        conversation_id: str,
        branch_id: str,
    ) -> tuple[KnowledgeAliasRecord | None, bool]:
        normalized = normalize_knowledge_text(alias)
        if not normalized:
            return None, False
        with self.storage.session() as db:
            existing = db.execute(
                "SELECT * FROM knowledge_aliases WHERE owner_id=? "
                "AND normalized_alias=?",
                (owner_id, normalized),
            ).fetchone()
            if existing:
                if existing["entity_id"] != entity_id:
                    return None, False
                record = KnowledgeAliasRecord.model_validate(dict(existing))
                return record, False
            alias_id = str(uuid4())
            db.execute(
                "INSERT INTO knowledge_aliases("
                "id, owner_id, entity_id, alias, normalized_alias, source_message_id"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    alias_id,
                    owner_id,
                    entity_id,
                    alias.strip(),
                    normalized,
                    source_message_id,
                ),
            )
            row = db.execute(
                "SELECT * FROM knowledge_aliases WHERE id=?", (alias_id,)
            ).fetchone()
        record = KnowledgeAliasRecord.model_validate(dict(row))
        if source_message_id:
            self._add_provenance(
                "alias",
                record.id,
                source_message_id,
                source_role,
                conversation_id,
                branch_id,
            )
        return record, True

    def _add_provenance(
        self,
        knowledge_kind: str,
        knowledge_id: str,
        source_message_id: str,
        source_role: KnowledgeSourceRole,
        conversation_id: str,
        branch_id: str,
    ) -> None:
        with self.storage.session() as db:
            existing = db.execute(
                "SELECT 1 FROM knowledge_provenance WHERE knowledge_kind=? "
                "AND knowledge_id=? AND source_message_id=?",
                (knowledge_kind, knowledge_id, source_message_id),
            ).fetchone()
            if existing:
                return
            db.execute(
                "INSERT INTO knowledge_provenance("
                "id, knowledge_kind, knowledge_id, source_message_id, source_role, "
                "conversation_id, branch_id"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    knowledge_kind,
                    knowledge_id,
                    source_message_id,
                    source_role,
                    conversation_id,
                    branch_id,
                ),
            )

    def provenance(
        self, knowledge_kind: str, knowledge_id: str
    ) -> list[KnowledgeProvenanceRecord]:
        with self.storage.session() as db:
            rows = db.execute(
                "SELECT * FROM knowledge_provenance WHERE knowledge_kind=? "
                "AND knowledge_id=? ORDER BY rowid",
                (knowledge_kind, knowledge_id),
            ).fetchall()
        return [KnowledgeProvenanceRecord.model_validate(dict(row)) for row in rows]

    def _record_row(self, row) -> KnowledgeRecord:
        return KnowledgeRecord.model_validate(dict(row))

    def _relation_row(self, row) -> KnowledgeRelationRecord:
        data = dict(row)
        data["symmetric"] = bool(data["symmetric"])
        return KnowledgeRelationRecord.model_validate(data)

    def promote(
        self,
        *,
        character_id: str,
        extraction: KnowledgeExtractionResult,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        timeline_id: str = "main",
    ) -> KnowledgePromotionResult:
        owner = self.get_or_create_owner(
            "character", character_id=character_id, timeline_id=timeline_id
        )
        result = KnowledgePromotionResult(owner_id=owner.id)
        source_ids = {
            "user": user_message_id,
            "assistant": assistant_message_id,
        }
        branch_id = conversation_id  # Temporary until #166 splits thread/branch IDs.

        for candidate in extraction.entities:
            _, created = self.resolve_entity(
                owner.id,
                candidate.name,
                source_message_id=source_ids[candidate.source_role],
                source_role=candidate.source_role,
                conversation_id=conversation_id,
                branch_id=branch_id,
            )
            result.entities_created += int(created)

        for candidate in extraction.aliases:
            entity, created = self.resolve_entity(
                owner.id,
                candidate.entity,
                source_message_id=source_ids[candidate.source_role],
                source_role=candidate.source_role,
                conversation_id=conversation_id,
                branch_id=branch_id,
            )
            result.entities_created += int(created)
            alias, alias_created = self.add_alias(
                owner.id,
                entity.id,
                candidate.alias,
                source_message_id=source_ids[candidate.source_role],
                source_role=candidate.source_role,
                conversation_id=conversation_id,
                branch_id=branch_id,
            )
            if alias is None:
                result.rejected.append(
                    f"alias_conflict:{normalize_knowledge_text(candidate.alias)}"
                )
            result.aliases_created += int(alias_created)

        for candidate in extraction.facts:
            created, merged, superseded = self._promote_record(
                owner_id=owner.id,
                subject=candidate.subject,
                predicate=candidate.predicate,
                value=candidate.value,
                source_role=candidate.source_role,
                epistemic_state=candidate.epistemic_state,
                confidence=candidate.confidence,
                conversation_id=conversation_id,
                branch_id=branch_id,
                source_message_id=source_ids[candidate.source_role],
                timeline_id=timeline_id,
            )
            result.records_created += int(created)
            result.records_merged += int(merged)
            result.records_superseded += superseded

        for candidate in extraction.preferences:
            created, merged, superseded = self._promote_record(
                owner_id=owner.id,
                subject=candidate.subject,
                predicate="likes" if candidate.sentiment == "like" else "dislikes",
                value=candidate.value,
                source_role=candidate.source_role,
                epistemic_state=candidate.epistemic_state,
                confidence=candidate.confidence,
                conversation_id=conversation_id,
                branch_id=branch_id,
                source_message_id=source_ids[candidate.source_role],
                timeline_id=timeline_id,
            )
            result.records_created += int(created)
            result.records_merged += int(merged)
            result.records_superseded += superseded

        for candidate in extraction.events:
            subject = candidate.entities[0] if candidate.entities else (
                "user" if candidate.source_role == "user" else character_id
            )
            created, merged, superseded = self._promote_record(
                owner_id=owner.id,
                subject=subject,
                predicate="event",
                value=candidate.description,
                source_role=candidate.source_role,
                epistemic_state=candidate.epistemic_state,
                confidence=candidate.confidence,
                conversation_id=conversation_id,
                branch_id=branch_id,
                source_message_id=source_ids[candidate.source_role],
                timeline_id=timeline_id,
                event=True,
                time_reference=candidate.time_reference,
            )
            result.records_created += int(created)
            result.records_merged += int(merged)
            result.records_superseded += superseded

        for candidate in extraction.relations:
            created, merged = self._promote_relation(
                owner_id=owner.id,
                subject=candidate.subject,
                predicate=candidate.predicate,
                object_name=candidate.object,
                source_role=candidate.source_role,
                epistemic_state=candidate.epistemic_state,
                confidence=candidate.confidence,
                conversation_id=conversation_id,
                branch_id=branch_id,
                source_message_id=source_ids[candidate.source_role],
                timeline_id=timeline_id,
            )
            result.relations_created += int(created)
            result.relations_merged += int(merged)

        return result

    def _promote_record(
        self,
        *,
        owner_id: str,
        subject: str,
        predicate: str,
        value: str,
        source_role: KnowledgeSourceRole,
        epistemic_state: EpistemicState,
        confidence: float,
        conversation_id: str,
        branch_id: str,
        source_message_id: str,
        timeline_id: str,
        event: bool = False,
        time_reference: str | None = None,
    ) -> tuple[bool, bool, int]:
        entity, _ = self.resolve_entity(
            owner_id,
            subject,
            source_message_id=source_message_id,
            source_role=source_role,
            conversation_id=conversation_id,
            branch_id=branch_id,
        )
        predicate_norm = normalize_knowledge_text(predicate).replace(" ", "_")
        value_norm = normalize_knowledge_text(value)
        with self.storage.session() as db:
            exact_fact = db.execute(
                "SELECT * FROM knowledge_records WHERE owner_id=? "
                "AND subject_entity_id=? AND predicate_normalized=? "
                "AND value_normalized=? AND status='active' AND record_type='FACT' "
                "AND timeline_id=? ORDER BY rowid DESC LIMIT 1",
                (
                    owner_id,
                    entity.id,
                    predicate_norm,
                    value_norm,
                    timeline_id,
                ),
            ).fetchone()
            if exact_fact is not None:
                db.execute(
                    "UPDATE knowledge_records SET confidence=MAX(confidence, ?), "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (confidence, exact_fact["id"]),
                )
                record_id = exact_fact["id"]
                merged = True
                created = False
                superseded = 0
            else:
                stored_epistemic = (
                    "inferred"
                    if source_role == "assistant" and epistemic_state == "confirmed"
                    else epistemic_state
                )
                stored_confidence = (
                    min(confidence, 0.65)
                    if source_role == "assistant" and epistemic_state == "confirmed"
                    else confidence
                )
                record_type = _record_type(
                    source_role=source_role,
                    epistemic_state=stored_epistemic,
                    text=value,
                    event=event,
                    time_reference=time_reference,
                )
                exact = db.execute(
                    "SELECT * FROM knowledge_records WHERE owner_id=? "
                    "AND subject_entity_id=? AND predicate_normalized=? "
                    "AND value_normalized=? AND record_type=? AND status='active' "
                    "AND timeline_id=? ORDER BY rowid DESC LIMIT 1",
                    (
                        owner_id,
                        entity.id,
                        predicate_norm,
                        value_norm,
                        record_type,
                        timeline_id,
                    ),
                ).fetchone()
                if exact is not None:
                    db.execute(
                        "UPDATE knowledge_records SET confidence=MAX(confidence, ?), "
                        "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (confidence, exact["id"]),
                    )
                    record_id = exact["id"]
                    merged = True
                    created = False
                    superseded = 0
                else:
                    record_id = str(uuid4())
                    temporal = _temporal_context(value, time_reference)
                    now = _now().isoformat()
                    db.execute(
                        "INSERT INTO knowledge_records("
                        "id, owner_id, subject_entity_id, predicate, "
                        "predicate_normalized, value, value_normalized, record_type, "
                        "status, confidence, epistemic_state, source_role, timeline_id, "
                        "temporal_context, observed_at, valid_from, known_from, "
                        "conversation_id, branch_id"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            record_id,
                            owner_id,
                            entity.id,
                            predicate,
                            predicate_norm,
                            value,
                            value_norm,
                            record_type,
                            confidence,
                            epistemic_state,
                            source_role,
                            timeline_id,
                            temporal,
                            now,
                            now if record_type in {"FACT", "EVENT"} else None,
                            now,
                            conversation_id,
                            branch_id,
                        ),
                    )
                    merged = False
                    created = True
                    superseded = 0
                    if (
                        record_type == "FACT"
                        and source_role == "user"
                        and epistemic_state == "confirmed"
                        and predicate_norm in _SINGLE_VALUE_PREDICATES
                    ):
                        rows = db.execute(
                            "SELECT id FROM knowledge_records WHERE owner_id=? "
                            "AND subject_entity_id=? AND predicate_normalized=? "
                            "AND status='active' AND record_type='FACT' AND id<>? "
                            "AND timeline_id=?",
                            (
                                owner_id,
                                entity.id,
                                predicate_norm,
                                record_id,
                                timeline_id,
                            ),
                        ).fetchall()
                        for row in rows:
                            db.execute(
                                "UPDATE knowledge_records SET status='superseded', "
                                "superseded_by=?, valid_to=?, updated_at=CURRENT_TIMESTAMP "
                                "WHERE id=?",
                                (record_id, now, row["id"]),
                            )
                            superseded += 1
        self._add_provenance(
            "record",
            record_id,
            source_message_id,
            source_role,
            conversation_id,
            branch_id,
        )
        return created, merged, superseded

    def _promote_relation(
        self,
        *,
        owner_id: str,
        subject: str,
        predicate: str,
        object_name: str,
        source_role: KnowledgeSourceRole,
        epistemic_state: EpistemicState,
        confidence: float,
        conversation_id: str,
        branch_id: str,
        source_message_id: str,
        timeline_id: str,
    ) -> tuple[bool, bool]:
        subject_entity, _ = self.resolve_entity(
            owner_id,
            subject,
            source_message_id=source_message_id,
            source_role=source_role,
            conversation_id=conversation_id,
            branch_id=branch_id,
        )
        object_entity, _ = self.resolve_entity(
            owner_id,
            object_name,
            source_message_id=source_message_id,
            source_role=source_role,
            conversation_id=conversation_id,
            branch_id=branch_id,
        )
        relation_type, inverse_type, symmetric = _relation_mapping(predicate)
        stored_epistemic = (
            "inferred"
            if source_role == "assistant" and epistemic_state == "confirmed"
            else epistemic_state
        )
        stored_confidence = (
            min(confidence, 0.65)
            if source_role == "assistant" and epistemic_state == "confirmed"
            else confidence
        )
        with self.storage.session() as db:
            row = db.execute(
                "SELECT * FROM knowledge_relations WHERE owner_id=? "
                "AND subject_entity_id=? AND relation_type=? AND object_entity_id=? "
                "AND status='active' AND timeline_id=? ORDER BY rowid DESC LIMIT 1",
                (
                    owner_id,
                    subject_entity.id,
                    relation_type,
                    object_entity.id,
                    timeline_id,
                ),
            ).fetchone()
            if row is not None:
                db.execute(
                    "UPDATE knowledge_relations SET confidence=MAX(confidence, ?), "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (stored_confidence, row["id"]),
                )
                relation_id = row["id"]
                created = False
                merged = True
            else:
                relation_id = str(uuid4())
                db.execute(
                    "INSERT INTO knowledge_relations("
                    "id, owner_id, subject_entity_id, relation_type, object_entity_id, "
                    "inverse_relation_type, symmetric, status, confidence, "
                    "epistemic_state, source_role, timeline_id, temporal_context, "
                    "conversation_id, branch_id"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, 'unknown', ?, ?)",
                    (
                        relation_id,
                        owner_id,
                        subject_entity.id,
                        relation_type,
                        object_entity.id,
                        inverse_type,
                        int(symmetric),
                        stored_confidence,
                        stored_epistemic,
                        source_role,
                        timeline_id,
                        conversation_id,
                        branch_id,
                    ),
                )
                created = True
                merged = False
        self._add_provenance(
            "relation",
            relation_id,
            source_message_id,
            source_role,
            conversation_id,
            branch_id,
        )
        return created, merged

    def active_records(self, owner_id: str) -> list[KnowledgeRecord]:
        with self.storage.session() as db:
            rows = db.execute(
                "SELECT * FROM knowledge_records WHERE owner_id=? "
                "AND status='active' ORDER BY rowid",
                (owner_id,),
            ).fetchall()
        return [self._record_row(row) for row in rows]

    def record_history(
        self, owner_id: str, subject: str, predicate: str
    ) -> list[KnowledgeRecord]:
        entity = self.find_entity(owner_id, subject)
        if entity is None:
            return []
        predicate_norm = normalize_knowledge_text(predicate).replace(" ", "_")
        with self.storage.session() as db:
            rows = db.execute(
                "SELECT * FROM knowledge_records WHERE owner_id=? "
                "AND subject_entity_id=? AND predicate_normalized=? ORDER BY rowid",
                (owner_id, entity.id, predicate_norm),
            ).fetchall()
        return [self._record_row(row) for row in rows]

    def invalidate_record(self, record_id: str) -> KnowledgeRecord:
        now = _now().isoformat()
        with self.storage.session() as db:
            row = db.execute(
                "SELECT * FROM knowledge_records WHERE id=?", (record_id,)
            ).fetchone()
            if row is None:
                raise KeyError("knowledge record not found")
            if row["status"] == "active":
                db.execute(
                    "UPDATE knowledge_records SET status='invalidated', "
                    "invalidated_at=?, known_until=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (now, now, record_id),
                )
            row = db.execute(
                "SELECT * FROM knowledge_records WHERE id=?", (record_id,)
            ).fetchone()
        return self._record_row(row)

    def find_entity(
        self, owner_id: str, name: str
    ) -> KnowledgeEntityRecord | None:
        normalized = normalize_knowledge_text(name)
        with self.storage.session() as db:
            row = db.execute(
                "SELECT e.* FROM knowledge_aliases a "
                "JOIN knowledge_entities e ON e.id=a.entity_id "
                "WHERE a.owner_id=? AND a.normalized_alias=?",
                (owner_id, normalized),
            ).fetchone()
            if row is None:
                row = db.execute(
                    "SELECT * FROM knowledge_entities WHERE owner_id=? "
                    "AND normalized_name=? ORDER BY rowid LIMIT 1",
                    (owner_id, normalized),
                ).fetchone()
        return self._entity_row(row) if row else None

    def lookup_records(
        self, owner_id: str, query: str, *, active_only: bool = True
    ) -> list[KnowledgeRecordLookupHit]:
        normalized = normalize_knowledge_text(query)
        entity = self.find_entity(owner_id, query)
        clauses = ["r.owner_id=?"]
        params: list[object] = [owner_id]
        if active_only:
            clauses.append("r.status='active'")
        with self.storage.session() as db:
            rows = db.execute(
                "SELECT r.*, e.canonical_name AS subject_name "
                "FROM knowledge_records r "
                "JOIN knowledge_entities e ON e.id=r.subject_entity_id "
                "WHERE " + " AND ".join(clauses) + " ORDER BY r.rowid",
                params,
            ).fetchall()
        result: list[KnowledgeRecordLookupHit] = []
        for row in rows:
            matched_on = None
            if entity and row["subject_entity_id"] == entity.id:
                matched_on = "subject"
            elif normalized and (
                normalized == row["value_normalized"]
                or normalized in row["value_normalized"]
            ):
                matched_on = "value"
            if matched_on:
                result.append(
                    KnowledgeRecordLookupHit(
                        record=self._record_row(row),
                        subject=row["subject_name"],
                        matched_on=matched_on,
                    )
                )
        return result

    def lookup_relations(
        self, owner_id: str, entity_name: str
    ) -> list[KnowledgeRelationLookupHit]:
        entity = self.find_entity(owner_id, entity_name)
        if entity is None:
            return []
        with self.storage.session() as db:
            rows = db.execute(
                "SELECT r.*, s.canonical_name AS subject_name, "
                "o.canonical_name AS object_name "
                "FROM knowledge_relations r "
                "JOIN knowledge_entities s ON s.id=r.subject_entity_id "
                "JOIN knowledge_entities o ON o.id=r.object_entity_id "
                "WHERE r.owner_id=? AND r.status='active' "
                "AND (r.subject_entity_id=? OR r.object_entity_id=?) "
                "ORDER BY r.rowid",
                (owner_id, entity.id, entity.id),
            ).fetchall()
        hits: list[KnowledgeRelationLookupHit] = []
        for row in rows:
            if row["subject_entity_id"] == entity.id:
                direction = "forward"
                effective = row["relation_type"]
            else:
                direction = "reverse"
                if row["symmetric"]:
                    effective = row["relation_type"]
                elif row["inverse_relation_type"]:
                    effective = row["inverse_relation_type"]
                else:
                    effective = f"reverse_of:{row['relation_type']}"
            hits.append(
                KnowledgeRelationLookupHit(
                    relation_id=row["id"],
                    direction=direction,
                    subject=row["subject_name"],
                    relation_type=row["relation_type"],
                    effective_relation_type=effective,
                    object=row["object_name"],
                    confidence=row["confidence"],
                )
            )
        return hits
