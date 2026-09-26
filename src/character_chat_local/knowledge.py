from __future__ import annotations

import json
import re
from contextlib import aclosing
from typing import Any

from pydantic import ValidationError

from .analysis import InputAnalyzer
from .models import (
    AliasCandidate,
    CharacterCore,
    ChatMessage,
    DynamicStateCandidate,
    EntityCandidate,
    EpistemicState,
    EventCandidate,
    FactCandidate,
    InputAnalysisResult,
    KnowledgeExtractionResult,
    KnowledgeSourceRole,
    PreferenceCandidate,
    RelationCandidate,
    RelationshipCandidate,
)
from .providers import ProviderError
from .task_router import TaskRouter

_JP_PREFERENCE = re.compile(
    r"(?:私は|僕は|俺は)?(?P<value>[^。、！？!?\n]{1,40}?)(?:が|を)"
    r"(?P<sentiment>大好き|好き|嫌い|苦手)"
)
_EN_PREFERENCE = re.compile(
    r"\bI\s+(?P<sentiment>love|like|hate|dislike)\s+(?P<value>[^.!?\n]{1,60})",
    re.IGNORECASE,
)
_JP_NAME = re.compile(r"(?:私の名前は|名前は)(?P<name>[^。、！？!?\n]{1,30})")
_JP_CALL_ME = re.compile(r"(?P<name>[^。、！？!?\n]{1,30})と呼んで")
_EN_CALL_ME = re.compile(r"\bcall me\s+(?P<name>[A-Za-z0-9_\- ]{1,40})", re.IGNORECASE)
_EN_NAME = re.compile(r"\bmy name is\s+(?P<name>[A-Za-z0-9_\- ]{1,40})", re.IGNORECASE)
_JP_RELATION = re.compile(
    r"(?P<subject>[一-龠々ぁ-んァ-ヶA-Za-z0-9_]{1,20})は"
    r"(?P<object>[一-龠々ぁ-んァ-ヶA-Za-z0-9_]{1,20})の"
    r"(?P<predicate>友達|親友|恋人|姉|兄|妹|弟|母|父|先生|先輩|後輩|同僚)"
)
_CURRENT_MARKERS = ("今", "いま", "現在", "ここにいる", "今いる", "I'm at", "I am at")
_FIRST_PERSON_MARKERS = ("私", "僕", "俺", "自分", "I ", "I'm", "I am")
_RELATIONSHIP_LABELS: tuple[tuple[str, float], ...] = (
    ("恋人", 0.08),
    ("親友", 0.06),
    ("友達", 0.04),
    ("大切", 0.04),
    ("特別", 0.04),
)
_TRUST_MARKERS = ("信頼", "信用", "trust")
_AFFECTION_MARKERS = ("大好き", "好き", "愛して", "love you", "care about you")


def _clean(value: str, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", value).strip(" 、。！？!?.,:;\"'")[:limit]


def _unique_models(items: list[Any], key_fields: tuple[str, ...], limit: int = 20):
    result = []
    seen: set[tuple[str, ...]] = set()
    for item in items:
        key = tuple(str(getattr(item, field, "")).casefold() for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


async def _collect_task_text(provider, assignment, messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    length = 0
    async with aclosing(
        provider.stream_chat(
            model=assignment.model,
            messages=messages,
            temperature=assignment.temperature,
        )
    ) as stream:
        async for chunk in stream:
            if not isinstance(chunk, str):
                raise ProviderError("knowledge extractor returned invalid chunk")
            length += len(chunk)
            if length > 12_000:
                raise ProviderError("knowledge extractor output exceeded limit")
            parts.append(chunk)
    return "".join(parts).strip()


class KnowledgeExtractor:
    """Structured post-final extraction with an optional task-routed model."""

    def __init__(self, task_router: TaskRouter | None = None):
        self.task_router = task_router
        self.analyzer = InputAnalyzer()

    async def extract(
        self,
        *,
        character: CharacterCore,
        user_message: str,
        final_assistant_message: str,
        input_analysis: InputAnalysisResult | None = None,
    ) -> KnowledgeExtractionResult:
        assignment = (
            self.task_router.resolve("knowledge_extractor")
            if self.task_router is not None
            else None
        )
        if assignment is None:
            return self._deterministic(
                character=character,
                user_message=user_message,
                final_assistant_message=final_assistant_message,
                input_analysis=input_analysis,
                strategy="deterministic-v1",
            )

        provider, task = assignment
        try:
            result = await self._model_extract(
                provider=provider,
                assignment=task,
                character=character,
                user_message=user_message,
                final_assistant_message=final_assistant_message,
                input_analysis=input_analysis,
            )
            return result
        except ProviderError:
            reason = "provider_error"
        except (ValueError, json.JSONDecodeError, ValidationError):
            reason = "parse_error"

        fallback = self._deterministic(
            character=character,
            user_message=user_message,
            final_assistant_message=final_assistant_message,
            input_analysis=input_analysis,
            strategy="model-fallback-v1",
        )
        return fallback.model_copy(update={"fallback_reason": reason})

    async def _model_extract(
        self,
        *,
        provider,
        assignment,
        character: CharacterCore,
        user_message: str,
        final_assistant_message: str,
        input_analysis: InputAnalysisResult | None,
    ) -> KnowledgeExtractionResult:
        schema = {
            "entities": [
                {
                    "name": "string",
                    "source_role": "user|assistant",
                    "epistemic_state": "confirmed|inferred|hypothesis",
                    "confidence": "0..1",
                }
            ],
            "facts": [
                {
                    "subject": "string",
                    "predicate": "string",
                    "value": "string",
                    "source_role": "user|assistant",
                    "epistemic_state": "confirmed|inferred|hypothesis",
                    "confidence": "0..1",
                }
            ],
            "relations": [
                {
                    "subject": "string",
                    "predicate": "string",
                    "object": "string",
                    "source_role": "user|assistant",
                    "epistemic_state": "confirmed|inferred|hypothesis",
                    "confidence": "0..1",
                }
            ],
            "events": [
                {
                    "description": "string",
                    "time_reference": "string|null",
                    "entities": ["string"],
                    "source_role": "user|assistant",
                    "epistemic_state": "confirmed|inferred|hypothesis",
                    "confidence": "0..1",
                }
            ],
            "preferences": [
                {
                    "subject": "string",
                    "value": "string",
                    "sentiment": "like|dislike",
                    "source_role": "user|assistant",
                    "epistemic_state": "confirmed|inferred|hypothesis",
                    "confidence": "0..1",
                }
            ],
            "aliases": [
                {
                    "entity": "string",
                    "alias": "string",
                    "source_role": "user|assistant",
                    "epistemic_state": "confirmed|inferred|hypothesis",
                    "confidence": "0..1",
                }
            ],
            "current_state_candidates": [
                {
                    "owner": "user|character",
                    "key": "emotion|location|concern|unresolved_event|recent_event",
                    "value": "string",
                    "source_role": "user|assistant",
                    "epistemic_state": "confirmed|inferred|hypothesis",
                    "confidence": "0..1",
                }
            ],
            "relationship_candidates": [
                {
                    "dimension": "relationship|trust|affection",
                    "label": "string",
                    "delta": "-1..1",
                    "source_role": "user|assistant",
                    "epistemic_state": "confirmed|inferred|hypothesis",
                    "confidence": "0..1",
                }
            ],
        }
        system = ChatMessage(
            role="system",
            content=(
                "Extract structured knowledge from DATA only. Return one JSON object and no prose. "
                "User statements can be confirmed when explicit. Assistant-origin claims must not "
                "be upgraded to confirmed merely because the assistant said them. Separate long-term "
                "knowledge from current state and relationship candidates. Keep at most 20 items per list. "
                "Schema: " + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            ),
        )
        data = {
            "character_name": character.name,
            "user_message": user_message,
            "final_assistant_message": final_assistant_message,
            "input_analysis": input_analysis.model_dump() if input_analysis else None,
        }
        raw = await _collect_task_text(
            provider,
            assignment,
            [system, ChatMessage(role="user", content=json.dumps(data, ensure_ascii=False))],
        )
        first = raw.find("{")
        last = raw.rfind("}")
        if first < 0 or last <= first:
            raise ValueError("knowledge extractor did not return an object")
        payload = json.loads(raw[first : last + 1])
        if not isinstance(payload, dict):
            raise ValueError("knowledge extractor result must be an object")
        payload["strategy"] = "model-v1"
        payload["fallback_reason"] = None
        result = KnowledgeExtractionResult.model_validate(payload)
        total = sum(
            len(getattr(result, field))
            for field in (
                "entities",
                "facts",
                "relations",
                "events",
                "preferences",
                "aliases",
                "current_state_candidates",
                "relationship_candidates",
            )
        )
        if total > 80:
            raise ValueError("knowledge extractor returned too many candidates")
        return result

    def _deterministic(
        self,
        *,
        character: CharacterCore,
        user_message: str,
        final_assistant_message: str,
        input_analysis: InputAnalysisResult | None,
        strategy: str,
    ) -> KnowledgeExtractionResult:
        user_analysis = input_analysis or self.analyzer.analyze(user_message)
        assistant_analysis = self.analyzer.analyze(
            final_assistant_message,
            known_people=[character.name],
        )

        entities: list[EntityCandidate] = []
        for name in [
            *user_analysis.entities,
            *user_analysis.people,
            *user_analysis.places,
        ]:
            cleaned = _clean(name, 200)
            if cleaned:
                entities.append(
                    EntityCandidate(
                        name=cleaned,
                        source_role="user",
                        epistemic_state="confirmed",
                        confidence=0.95,
                    )
                )
        for name in [
            *assistant_analysis.entities,
            *assistant_analysis.people,
            *assistant_analysis.places,
        ]:
            cleaned = _clean(name, 200)
            if cleaned:
                entities.append(
                    EntityCandidate(
                        name=cleaned,
                        source_role="assistant",
                        epistemic_state="hypothesis",
                        confidence=0.45,
                    )
                )

        facts: list[FactCandidate] = []
        if user_analysis.explicit_memory_request:
            facts.append(
                FactCandidate(
                    subject="user",
                    predicate="explicit_memory",
                    value=_clean(user_message),
                    source_role="user",
                    epistemic_state="confirmed",
                    confidence=0.98,
                )
            )

        preferences: list[PreferenceCandidate] = []
        preferences.extend(
            self._preferences(
                user_message,
                subject="user",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.95,
            )
        )
        preferences.extend(
            self._preferences(
                final_assistant_message,
                subject=character.name,
                source_role="assistant",
                epistemic_state="inferred",
                confidence=0.65,
            )
        )

        aliases: list[AliasCandidate] = []
        aliases.extend(
            self._aliases(
                user_message,
                entity="user",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.98,
            )
        )
        aliases.extend(
            self._aliases(
                final_assistant_message,
                entity=character.name,
                source_role="assistant",
                epistemic_state="inferred",
                confidence=0.65,
            )
        )
        for alias in aliases:
            facts.append(
                FactCandidate(
                    subject=alias.entity,
                    predicate="alias",
                    value=alias.alias,
                    source_role=alias.source_role,
                    epistemic_state=alias.epistemic_state,
                    confidence=alias.confidence,
                )
            )

        relations = self._relations(user_message, "user", "confirmed", 0.9)
        relations.extend(
            self._relations(
                final_assistant_message, "assistant", "inferred", 0.6
            )
        )

        events: list[EventCandidate] = []
        if user_analysis.time_references:
            events.append(
                EventCandidate(
                    description=_clean(user_message, 800),
                    time_reference=user_analysis.time_references[0],
                    entities=user_analysis.entities[:8],
                    source_role="user",
                    epistemic_state="confirmed",
                    confidence=0.9,
                )
            )
        if assistant_analysis.time_references:
            events.append(
                EventCandidate(
                    description=_clean(final_assistant_message, 800),
                    time_reference=assistant_analysis.time_references[0],
                    entities=assistant_analysis.entities[:8],
                    source_role="assistant",
                    epistemic_state="hypothesis",
                    confidence=0.45,
                )
            )

        current_states = self._state_candidates(
            user_message,
            user_analysis,
            owner="user",
            source_role="user",
            epistemic_state="confirmed",
            confidence=0.9,
        )
        current_states.extend(
            self._state_candidates(
                final_assistant_message,
                assistant_analysis,
                owner="character",
                source_role="assistant",
                epistemic_state="inferred",
                confidence=0.65,
            )
        )

        relationship_candidates = self._relationship_candidates(
            user_message,
            source_role="user",
            epistemic_state="confirmed",
            confidence=0.9,
            scale=1.0,
        )
        relationship_candidates.extend(
            self._relationship_candidates(
                final_assistant_message,
                source_role="assistant",
                epistemic_state="inferred",
                confidence=0.65,
                scale=0.5,
            )
        )

        return KnowledgeExtractionResult(
            strategy=strategy,
            entities=_unique_models(entities, ("name", "source_role")),
            facts=_unique_models(facts, ("subject", "predicate", "value", "source_role")),
            relations=_unique_models(
                relations, ("subject", "predicate", "object", "source_role")
            ),
            events=_unique_models(events, ("description", "source_role"), 10),
            preferences=_unique_models(
                preferences, ("subject", "value", "sentiment", "source_role")
            ),
            aliases=_unique_models(aliases, ("entity", "alias", "source_role")),
            current_state_candidates=_unique_models(
                current_states, ("owner", "key", "value", "source_role")
            ),
            relationship_candidates=_unique_models(
                relationship_candidates,
                ("dimension", "label", "source_role"),
            ),
        )

    @staticmethod
    def _preferences(
        text: str,
        *,
        subject: str,
        source_role: KnowledgeSourceRole,
        epistemic_state: EpistemicState,
        confidence: float,
    ) -> list[PreferenceCandidate]:
        items: list[PreferenceCandidate] = []
        for match in _JP_PREFERENCE.finditer(text):
            value = _clean(match.group("value"), 300)
            if not value:
                continue
            items.append(
                PreferenceCandidate(
                    subject=subject,
                    value=value,
                    sentiment="dislike"
                    if match.group("sentiment") in {"嫌い", "苦手"}
                    else "like",
                    source_role=source_role,
                    epistemic_state=epistemic_state,
                    confidence=confidence,
                )
            )
        for match in _EN_PREFERENCE.finditer(text):
            value = _clean(match.group("value"), 300)
            if not value:
                continue
            items.append(
                PreferenceCandidate(
                    subject=subject,
                    value=value,
                    sentiment="dislike"
                    if match.group("sentiment").casefold() in {"hate", "dislike"}
                    else "like",
                    source_role=source_role,
                    epistemic_state=epistemic_state,
                    confidence=confidence,
                )
            )
        return items

    @staticmethod
    def _aliases(
        text: str,
        *,
        entity: str,
        source_role: KnowledgeSourceRole,
        epistemic_state: EpistemicState,
        confidence: float,
    ) -> list[AliasCandidate]:
        result: list[AliasCandidate] = []
        for regex in (_JP_NAME, _JP_CALL_ME, _EN_CALL_ME, _EN_NAME):
            for match in regex.finditer(text):
                alias = _clean(match.group("name"), 200)
                if alias:
                    result.append(
                        AliasCandidate(
                            entity=entity,
                            alias=alias,
                            source_role=source_role,
                            epistemic_state=epistemic_state,
                            confidence=confidence,
                        )
                    )
        return result

    @staticmethod
    def _relations(
        text: str,
        source_role: KnowledgeSourceRole,
        epistemic_state: EpistemicState,
        confidence: float,
    ) -> list[RelationCandidate]:
        return [
            RelationCandidate(
                subject=_clean(match.group("subject"), 200),
                predicate=_clean(match.group("predicate"), 120),
                object=_clean(match.group("object"), 200),
                source_role=source_role,
                epistemic_state=epistemic_state,
                confidence=confidence,
            )
            for match in _JP_RELATION.finditer(text)
        ]

    @staticmethod
    def _state_candidates(
        text: str,
        analysis: InputAnalysisResult,
        *,
        owner: str,
        source_role: KnowledgeSourceRole,
        epistemic_state: EpistemicState,
        confidence: float,
    ) -> list[DynamicStateCandidate]:
        result: list[DynamicStateCandidate] = []
        folded = text.casefold()
        current = any(marker.casefold() in folded for marker in _CURRENT_MARKERS)
        first_person = any(
            marker.casefold() in folded for marker in _FIRST_PERSON_MARKERS
        )
        if analysis.places and (current or first_person):
            result.append(
                DynamicStateCandidate(
                    owner=owner,
                    key="location",
                    value=analysis.places[0],
                    source_role=source_role,
                    epistemic_state=epistemic_state,
                    confidence=confidence,
                )
            )
        if analysis.emotions and (first_person or owner == "user"):
            result.append(
                DynamicStateCandidate(
                    owner=owner,
                    key="emotion",
                    value=analysis.emotions[0],
                    source_role=source_role,
                    epistemic_state=epistemic_state,
                    confidence=confidence,
                )
            )
        if "anxiety" in analysis.emotions or any(
            marker in text for marker in ("心配", "不安", "気がかり")
        ):
            result.append(
                DynamicStateCandidate(
                    owner=owner,
                    key="concern",
                    value=_clean(text, 500),
                    source_role=source_role,
                    epistemic_state=epistemic_state,
                    confidence=max(0.0, confidence - 0.05),
                )
            )
        return result

    @staticmethod
    def _relationship_candidates(
        text: str,
        *,
        source_role: KnowledgeSourceRole,
        epistemic_state: EpistemicState,
        confidence: float,
        scale: float,
    ) -> list[RelationshipCandidate]:
        folded = text.casefold()
        result: list[RelationshipCandidate] = []
        if any(token in text for token in ("私たち", "あなた", "君", "二人")) or any(
            token in folded for token in ("we ", "you ")
        ):
            for label, delta in _RELATIONSHIP_LABELS:
                if label in text:
                    result.append(
                        RelationshipCandidate(
                            dimension="relationship",
                            label=label,
                            delta=delta * scale,
                            source_role=source_role,
                            epistemic_state=epistemic_state,
                            confidence=confidence,
                        )
                    )
                    break
            if any(marker.casefold() in folded for marker in _TRUST_MARKERS):
                result.append(
                    RelationshipCandidate(
                        dimension="trust",
                        label="trust signal",
                        delta=0.05 * scale,
                        source_role=source_role,
                        epistemic_state=epistemic_state,
                        confidence=confidence,
                    )
                )
            if any(marker.casefold() in folded for marker in _AFFECTION_MARKERS):
                result.append(
                    RelationshipCandidate(
                        dimension="affection",
                        label="affection signal",
                        delta=0.04 * scale,
                        source_role=source_role,
                        epistemic_state=epistemic_state,
                        confidence=confidence,
                    )
                )
        return result
