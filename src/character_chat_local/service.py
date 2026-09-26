from __future__ import annotations

import asyncio
import sqlite3
from contextlib import aclosing
from typing import Any, Protocol

import httpx

from .analysis import InputAnalyzer
from .guardian import Guardian
from .knowledge import KnowledgeExtractor
from .models import (
    CharacterCore,
    ChatMessage,
    ChatRunResult,
    ConversationInfo,
    ConversationSummary,
    GuardianResult,
    QualityMode,
    RecallBundle,
    TurnStepResult,
    TurnTrace,
)
from .prompting import (
    DEFAULT_PROMPT_BYTES,
    DEFAULT_PROMPT_TOKENS,
    build_context,
)
from .providers import AIProvider, ProviderError
from .quality import LightweightDraftChecker
from .recall import RecallEngine
from .state import StateCandidateCommitter
from .storage import Storage
from .summary import SummaryEngine
from .task_router import TaskRouter


class ProgressCallback(Protocol):
    async def __call__(self, event: dict[str, Any]) -> None: ...


class ChunkCallback(Protocol):
    async def __call__(self, part: str) -> None: ...


class QualityRejected(RuntimeError):
    def __init__(
        self,
        evaluation_id: str,
        guardian: GuardianResult,
        trace: TurnTrace | None = None,
    ):
        super().__init__("response did not pass quality checks")
        self.evaluation_id = evaluation_id
        self.guardian = guardian
        self.trace = trace


async def _collect(
    provider: AIProvider,
    model: str,
    messages: list[ChatMessage],
    temperature: float,
    on_chunk: ChunkCallback | None = None,
) -> str:
    parts: list[str] = []
    length = 0
    try:
        async with aclosing(
            provider.stream_chat(
                model=model, messages=messages, temperature=temperature
            )
        ) as stream:
            async for part in stream:
                if not isinstance(part, str):
                    raise ProviderError("provider returned an invalid text chunk")
                length += len(part)
                if length > 8000:
                    raise ProviderError("provider response exceeded output limit")
                parts.append(part)
                if on_chunk is not None:
                    await on_chunk(part)
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        raise ProviderError("provider request failed") from exc
    return "".join(parts).strip()


class ChatService:
    """Single-turn orchestrator with bounded quality-mode paths."""

    def __init__(
        self,
        storage: Storage,
        *,
        max_prompt_bytes: int = DEFAULT_PROMPT_BYTES,
        max_prompt_tokens: int = DEFAULT_PROMPT_TOKENS,
        timeout: float = 300.0,
        default_quality_mode: QualityMode = "balanced",
        task_router: TaskRouter | None = None,
    ):
        if default_quality_mode not in {"fast", "balanced", "strict"}:
            raise ValueError("invalid default quality mode")
        self.storage = storage
        self.analyzer = InputAnalyzer()
        self.recall = RecallEngine()
        self.guardian = Guardian()
        self.lightweight = LightweightDraftChecker()
        self.summary = SummaryEngine()
        self.knowledge = KnowledgeExtractor(task_router)
        self.state_committer = StateCandidateCommitter(storage)
        self.max_prompt_bytes = max_prompt_bytes
        self.max_prompt_tokens = max_prompt_tokens
        self.timeout = timeout
        self.default_quality_mode = default_quality_mode

    def resolve_quality_mode(
        self,
        character: CharacterCore,
        conversation: ConversationInfo | None = None,
    ) -> QualityMode:
        return (
            (conversation.quality_mode if conversation is not None else None)
            or character.quality_mode
            or self.default_quality_mode
        )

    @staticmethod
    def _record(
        trace: TurnTrace,
        name: str,
        *,
        status: str = "completed",
        **details: Any,
    ) -> None:
        trace.steps.append(TurnStepResult(name=name, status=status, details=details))

    async def run(
        self,
        *,
        provider: AIProvider,
        model: str,
        character: CharacterCore,
        user_input: str,
        history: list[ChatMessage] | None = None,
        conversation_id: str | None = None,
        temperature: float = 0.8,
        on_event: ProgressCallback | None = None,
        generation_id: str | None = None,
    ) -> ChatRunResult:
        if not user_input.strip() or len(user_input) > 4000:
            raise ValueError("input must contain 1 to 4000 non-blank characters")
        if not model.strip() or len(model) > 200 or not 0 <= temperature <= 2:
            raise ValueError("invalid model or temperature")

        conversation = None
        summary = ConversationSummary()
        if conversation_id:
            if history is not None:
                raise ValueError("persisted conversations use server-owned history")
            with self.storage.context_snapshot(conversation_id) as (
                conversation,
                saved,
                rows,
            ):
                if conversation.character_id != character.id:
                    raise ValueError("character does not match conversation")
                summary, recent = self.summary.prepare(saved, rows)
                history = [ChatMessage(role=m.role, content=m.content) for m in recent]
        history = history or []

        quality_mode = self.resolve_quality_mode(character, conversation)
        trace = TurnTrace(quality_mode=quality_mode)

        memories = [
            *self.storage.list_memories(character.id),
            *self.storage.context_state_memories(character.id),
        ]
        known_entities = [
            entity
            for memory in memories
            for entity in memory.entities
            if entity.strip()
        ]
        analysis = self.analyzer.analyze(
            user_input,
            known_entities=known_entities,
            known_people=[character.name],
        )
        self._record(trace, "input_analysis", **analysis.model_dump())

        primary = self.recall.recall(user_input, memories)
        self._record(
            trace,
            "primary_recall",
            hits=len(primary.hits),
            approx_tokens=primary.approx_tokens,
        )
        secondary = RecallBundle()
        attempts: list[dict[str, Any]] = []
        repaired = False
        regenerated_for_recall = False

        async def emit(event_type: str, **payload: Any) -> None:
            if on_event is not None:
                await on_event({"type": event_type, **payload})

        async def generate(
            hits,
            purpose: str,
            repair: str | None = None,
        ) -> str:
            context = build_context(
                character=character,
                history=history,
                user_input=user_input,
                recalled=hits,
                summary=summary,
                memories=memories,
                repair=repair,
                max_prompt_bytes=self.max_prompt_bytes,
                max_prompt_tokens=self.max_prompt_tokens,
            )
            messages = context.messages
            self._record(
                trace,
                "context_build",
                purpose=purpose,
                recalled=len(hits),
                debug=context.debug.model_dump(),
            )

            async def draft_chunk(part: str) -> None:
                await emit("draft_delta", text=part)

            text = await _collect(
                provider,
                model,
                messages,
                temperature,
                draft_chunk if purpose == "initial" else None,
            )
            attempts.append({"purpose": purpose, "text": text})
            self._record(
                trace,
                "draft_generation",
                purpose=purpose,
                characters=len(text),
                attempt=len(attempts),
            )
            return text

        def full_guardian(text: str, purpose: str) -> GuardianResult:
            result = self.guardian.validate(text, character)
            attempts[-1]["guardian"] = result.model_dump()
            self._record(
                trace,
                "guardian",
                purpose=purpose,
                passed=result.passed,
                findings=[item.category for item in result.findings],
            )
            return result

        try:
            async with asyncio.timeout(self.timeout):
                await emit("phase", phase="generating")
                draft = await generate(primary.hits, "initial")
                text = draft

                await emit("phase", phase="checking")
                recalled_ids = {hit.memory.id for hit in primary.hits}
                lightweight = self.lightweight.check(
                    draft,
                    character,
                    memories=memories,
                    recalled_ids=recalled_ids,
                )
                attempts[-1]["lightweight"] = lightweight.model_dump()
                self._record(
                    trace,
                    "lightweight_check",
                    passed=lightweight.passed,
                    requires_inspection=lightweight.requires_inspection,
                    findings=[item.category for item in lightweight.findings],
                    inspect_signals=lightweight.inspect_signals,
                )
                guardian = GuardianResult(
                    passed=lightweight.passed,
                    findings=lightweight.findings,
                )
                hits = list(primary.hits)

                secondary_probe = None
                probe_signal = False
                if quality_mode == "balanced":
                    secondary_probe = self.recall.recall(
                        draft,
                        memories,
                        exclude_ids=recalled_ids,
                    )
                    probe_signal = bool(secondary_probe.hits)
                inspect = quality_mode == "strict" or (
                    quality_mode == "balanced"
                    and (lightweight.requires_inspection or probe_signal)
                )
                if quality_mode == "fast":
                    self._record(
                        trace,
                        "draft_analysis",
                        status="skipped",
                        reason="fast_mode",
                    )
                    self._record(
                        trace,
                        "secondary_recall",
                        status="skipped",
                        reason="fast_mode",
                    )
                    self._record(
                        trace,
                        "guardian",
                        status="skipped",
                        reason="fast_mode_uses_lightweight_gate",
                    )
                elif inspect:
                    analysis_signals = list(lightweight.inspect_signals)
                    if probe_signal:
                        analysis_signals.append("secondary_recall_probe")
                    self._record(
                        trace,
                        "draft_analysis",
                        inspect_signals=analysis_signals,
                        forced=quality_mode == "strict",
                    )
                    secondary = (
                        secondary_probe
                        if secondary_probe is not None
                        else self.recall.recall(
                            draft,
                            memories,
                            exclude_ids=recalled_ids,
                        )
                    )
                    self._record(
                        trace,
                        "secondary_recall",
                        hits=len(secondary.hits),
                        approx_tokens=secondary.approx_tokens,
                    )
                    hits.extend(secondary.hits)
                    if secondary.hits:
                        regenerated_for_recall = True
                        await emit("phase", phase="secondary_recall")
                        text = await generate(hits, "secondary_recall")
                        await emit("phase", phase="checking")
                        guardian = full_guardian(text, "secondary_recall")
                    else:
                        guardian = full_guardian(text, "initial")
                else:
                    self._record(
                        trace,
                        "draft_analysis",
                        status="skipped",
                        reason="no_inspect_signal",
                    )
                    self._record(
                        trace,
                        "secondary_recall",
                        status="skipped",
                        reason="no_inspect_signal",
                    )
                    self._record(
                        trace,
                        "guardian",
                        status="skipped",
                        reason="balanced_lightweight_pass",
                    )

                if quality_mode != "fast" and not guardian.passed:
                    repaired = True
                    await emit("phase", phase="repairing")
                    repair = "; ".join(
                        f"{finding.category}: {finding.reason}"
                        for finding in guardian.findings
                    )
                    text = await generate(hits, "quality_repair", repair)
                    await emit("phase", phase="checking")
                    guardian = full_guardian(text, "quality_repair")

                if quality_mode == "strict":
                    final_guardian = self.guardian.validate(text, character)
                    self._record(
                        trace,
                        "final_guardian",
                        passed=final_guardian.passed,
                        findings=[item.category for item in final_guardian.findings],
                    )
                    guardian = final_guardian
                else:
                    self._record(
                        trace,
                        "final_guardian",
                        status="skipped",
                        reason=f"{quality_mode}_mode",
                    )
        except TimeoutError as exc:
            raise ProviderError("generation timed out") from exc

        metadata = {
            "provider": provider.id,
            "model": model,
            "generation_id": generation_id,
            "quality_mode": quality_mode,
            "attempts": attempts,
            "turn_trace": trace.model_dump(),
        }
        if not guardian.passed:
            self._record(
                trace,
                "finalize",
                status="skipped",
                reason="quality_rejected",
            )
            self._record(
                trace,
                "memory_extraction",
                status="skipped",
                reason="final_not_accepted",
            )
            self._record(
                trace,
                "state_update",
                status="skipped",
                reason="final_not_accepted",
            )
            evaluation_id = self.storage.save_evaluation(
                conversation_id, draft, "", guardian, metadata
            )
            self._record(trace, "evaluation_log", evaluation_id=evaluation_id)
            raise QualityRejected(evaluation_id, guardian, trace)

        pending_extraction = None
        extraction_failure: str | None = None
        if conversation is not None:
            try:
                pending_extraction = await self.knowledge.extract(
                    character=character,
                    user_message=user_input,
                    final_assistant_message=text,
                    input_analysis=analysis,
                )
            except (ValueError, ProviderError) as exc:
                extraction_failure = type(exc).__name__

        commit = None
        evaluation_id: str | None = None
        if conversation is not None:
            commit = self.storage.commit_turn(
                conversation=conversation,
                user_input=user_input,
                text=text,
                provider=provider.id,
                model=model,
                summary=summary,
                draft=draft,
                guardian=guardian,
                metadata=metadata,
            )
            evaluation_id = commit.evaluation_id
            self._record(
                trace,
                "finalize",
                persisted=True,
                user_message_id=commit.user_message_id,
                assistant_message_id=commit.assistant_message_id,
            )
        else:
            evaluation_id = self.storage.save_evaluation(
                None, draft, text, guardian, metadata
            )
            self._record(
                trace,
                "finalize",
                persisted=False,
                evaluation_id=evaluation_id,
            )

        if conversation is not None and commit is not None:
            if pending_extraction is None:
                self._record(
                    trace,
                    "memory_extraction",
                    status="failed",
                    reason=extraction_failure or "extractor_failed",
                )
                self._record(
                    trace,
                    "state_update",
                    status="skipped",
                    reason="knowledge_extraction_failed",
                )
            else:
                try:
                    extraction_record = self.storage.save_knowledge_extraction(
                        conversation_id=conversation.id,
                        user_message_id=commit.user_message_id,
                        assistant_message_id=commit.assistant_message_id,
                        extraction=pending_extraction,
                    )
                except (ValueError, KeyError, sqlite3.Error) as exc:
                    self._record(
                        trace,
                        "memory_extraction",
                        status="failed",
                        reason=type(exc).__name__,
                    )
                    self._record(
                        trace,
                        "state_update",
                        status="skipped",
                        reason="knowledge_persistence_failed",
                    )
                else:
                    self._record(
                        trace,
                        "memory_extraction",
                        strategy=pending_extraction.strategy,
                        fallback_reason=pending_extraction.fallback_reason,
                        extraction_id=extraction_record.id,
                        long_term_candidates=(
                            len(pending_extraction.entities)
                            + len(pending_extraction.facts)
                            + len(pending_extraction.relations)
                            + len(pending_extraction.events)
                            + len(pending_extraction.preferences)
                            + len(pending_extraction.aliases)
                        ),
                        current_state_candidates=len(
                            pending_extraction.current_state_candidates
                        ),
                        relationship_candidates=len(
                            pending_extraction.relationship_candidates
                        ),
                    )
                    metadata["knowledge_extraction_id"] = extraction_record.id
                    try:
                        state_result = self.state_committer.commit(
                            character_id=character.id,
                            extraction=pending_extraction,
                            user_message_id=commit.user_message_id,
                            assistant_message_id=commit.assistant_message_id,
                        )
                    except (ValueError, KeyError, sqlite3.Error) as exc:
                        self._record(
                            trace,
                            "state_update",
                            status="failed",
                            reason=type(exc).__name__,
                        )
                    else:
                        self._record(
                            trace,
                            "state_update",
                            dynamic_committed=len(state_result.dynamic_states),
                            relationship_committed=len(
                                state_result.relationship_states
                            ),
                            rejected=state_result.rejected,
                        )
                        metadata["state_commit"] = {
                            "dynamic": len(state_result.dynamic_states),
                            "relationship": len(
                                state_result.relationship_states
                            ),
                            "rejected": state_result.rejected,
                        }
        else:
            self._record(
                trace,
                "memory_extraction",
                status="skipped",
                reason="no_persisted_turn",
            )
            self._record(
                trace,
                "state_update",
                status="skipped",
                reason="no_persisted_turn",
            )

        self._record(trace, "evaluation_log", persisted=True)
        metadata["turn_trace"] = trace.model_dump()
        if evaluation_id is not None:
            try:
                self.storage.update_evaluation_metadata(evaluation_id, metadata)
            except (KeyError, sqlite3.Error):
                pass

        return ChatRunResult(
            text=text,
            draft=draft,
            primary_recall=primary,
            secondary_recall=secondary,
            guardian=guardian,
            quality_mode=quality_mode,
            trace=trace,
            regenerated_for_recall=regenerated_for_recall,
            repaired=repaired,
        )
