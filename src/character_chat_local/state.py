from __future__ import annotations

from uuid import uuid4

from .models import KnowledgeExtractionResult, StateCommitResult
from .storage import Storage


class StateCandidateCommitter:
    """Applies deterministic safety rules before committing post-final state."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def commit(
        self,
        *,
        character_id: str,
        extraction: KnowledgeExtractionResult,
        user_message_id: str,
        assistant_message_id: str,
    ) -> StateCommitResult:
        result = StateCommitResult()
        source_ids = {
            "user": user_message_id,
            "assistant": assistant_message_id,
        }

        current_dynamic = {
            (item.owner, item.key): item
            for item in self.storage.latest_dynamic_states(character_id)
        }
        for candidate in extraction.current_state_candidates:
            reason = self._dynamic_rejection(candidate)
            if reason:
                result.rejected.append(reason)
                continue
            existing = current_dynamic.get((candidate.owner, candidate.key))
            if existing and existing.value.casefold() == candidate.value.casefold():
                result.rejected.append(
                    f"duplicate_state:{candidate.owner}:{candidate.key}"
                )
                continue
            record = self.storage.append_dynamic_state(
                character_id=character_id,
                owner=candidate.owner,
                key=candidate.key,
                value=candidate.value,
                confidence=candidate.confidence,
                epistemic_state=candidate.epistemic_state,
                source_message_id=source_ids[candidate.source_role],
            )
            current_dynamic[(candidate.owner, candidate.key)] = record
            result.dynamic_states.append(record)

        current_relationship = {
            item.dimension: item
            for item in self.storage.latest_relationship_states(character_id)
        }
        change_id = str(uuid4())
        for candidate in extraction.relationship_candidates:
            reason = self._relationship_rejection(candidate)
            if reason:
                result.rejected.append(reason)
                continue
            current = current_relationship.get(candidate.dimension)
            previous_score = current.score if current else 0.0
            max_delta = self._max_relationship_delta(
                candidate.source_role, candidate.epistemic_state
            )
            applied_delta = max(-max_delta, min(max_delta, candidate.delta))
            next_score = max(-1.0, min(1.0, previous_score + applied_delta))
            if (
                current
                and abs(next_score - current.score) < 1e-9
                and current.label.casefold() == candidate.label.casefold()
            ):
                result.rejected.append(f"duplicate_relationship:{candidate.dimension}")
                continue
            record = self.storage.append_relationship_state(
                character_id=character_id,
                dimension=candidate.dimension,
                score=next_score,
                label=candidate.label,
                confidence=candidate.confidence,
                epistemic_state=candidate.epistemic_state,
                source_message_id=source_ids[candidate.source_role],
                change_id=change_id,
            )
            current_relationship[candidate.dimension] = record
            result.relationship_states.append(record)

        return result

    @staticmethod
    def _dynamic_rejection(candidate) -> str | None:
        if candidate.epistemic_state == "hypothesis":
            return f"hypothesis_state:{candidate.owner}:{candidate.key}"
        if candidate.confidence < 0.6:
            return f"low_confidence_state:{candidate.owner}:{candidate.key}"
        if candidate.owner == "user" and candidate.source_role != "user":
            return f"source_owner_mismatch:user:{candidate.key}"
        if candidate.owner == "character" and candidate.source_role != "assistant":
            return f"source_owner_mismatch:character:{candidate.key}"
        return None

    @staticmethod
    def _relationship_rejection(candidate) -> str | None:
        if candidate.epistemic_state == "hypothesis":
            return f"hypothesis_relationship:{candidate.dimension}"
        if candidate.confidence < 0.6:
            return f"low_confidence_relationship:{candidate.dimension}"
        return None

    @staticmethod
    def _max_relationship_delta(source_role: str, epistemic_state: str) -> float:
        if source_role == "assistant":
            return 0.03
        if epistemic_state == "confirmed":
            return 0.08
        return 0.04
