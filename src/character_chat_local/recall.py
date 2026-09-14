from __future__ import annotations

import re
from collections.abc import Iterable

from .models import MemoryRecord, RecallBundle, RecallHit

_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[ぁ-んァ-ヶ一-龠々]+")


def _terms(text: str) -> set[str]:
    return {token.casefold() for token in _WORD_RE.findall(text) if token.strip()}


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class RecallEngine:
    def score(self, query: str, memory: MemoryRecord) -> RecallHit:
        query_fold = query.casefold()
        query_terms = _terms(query)
        memory_terms = _terms(memory.content)
        reasons: list[str] = []
        score = 0.0

        trigger_matches = [trigger for trigger in memory.triggers if trigger.casefold() in query_fold]
        if trigger_matches:
            score += 0.35
            reasons.append(f"trigger:{','.join(trigger_matches[:3])}")

        entity_matches = [entity for entity in memory.entities if entity.casefold() in query_fold]
        if entity_matches:
            score += 0.20
            reasons.append(f"entity:{','.join(entity_matches[:3])}")

        if query_terms and memory_terms:
            overlap = len(query_terms & memory_terms) / len(query_terms | memory_terms)
            if overlap:
                score += min(0.20, overlap * 0.6)
                reasons.append(f"lexical:{overlap:.2f}")

        score += memory.importance * 0.15
        score += memory.confidence * 0.10
        reasons.append(f"importance:{memory.importance:.2f}")
        reasons.append(f"confidence:{memory.confidence:.2f}")
        return RecallHit(memory=memory, score=min(score, 1.0), reasons=reasons)

    def recall(
        self,
        query: str,
        memories: Iterable[MemoryRecord],
        *,
        token_budget: int = 1200,
        exclude_ids: set[str] | None = None,
    ) -> RecallBundle:
        excluded = exclude_ids or set()
        candidates = [
            self.score(query, memory)
            for memory in memories
            if memory.id not in excluded
        ]
        candidates = [
            hit for hit in candidates if hit.score >= hit.memory.activation_threshold
        ]
        candidates.sort(key=lambda hit: hit.score, reverse=True)

        selected: list[RecallHit] = []
        used = 0
        for hit in candidates:
            cost = _approx_tokens(hit.memory.content)
            if selected and used + cost > token_budget:
                continue
            if cost > token_budget and selected:
                continue
            selected.append(hit)
            used += cost
            if used >= token_budget:
                break
        return RecallBundle(hits=selected, approx_tokens=used)
