from __future__ import annotations

import asyncio
from contextlib import aclosing
from typing import Any, Awaitable, Callable

import httpx

from .guardian import Guardian
from .models import (
    CharacterCore,
    ChatMessage,
    ChatRunResult,
    ConversationSummary,
    GuardianResult,
    RecallBundle,
)
from .prompting import DEFAULT_PROMPT_BYTES, build_messages
from .providers import AIProvider, ProviderError
from .recall import RecallEngine
from .storage import Storage
from .summary import SummaryEngine


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


class QualityRejected(RuntimeError):
    def __init__(self, evaluation_id: str, guardian: GuardianResult):
        super().__init__("response did not pass quality checks")
        self.evaluation_id = evaluation_id
        self.guardian = guardian


async def _collect(
    provider: AIProvider,
    model: str,
    messages: list[ChatMessage],
    temperature: float,
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
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
    def __init__(
        self,
        storage: Storage,
        *,
        max_prompt_bytes: int = DEFAULT_PROMPT_BYTES,
        timeout: float = 300.0,
    ):
        self.storage = storage
        self.recall = RecallEngine()
        self.guardian = Guardian()
        self.summary = SummaryEngine()
        self.max_prompt_bytes = max_prompt_bytes
        self.timeout = timeout

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
        memories = self.storage.list_memories(character.id)
        primary = self.recall.recall(user_input, memories)
        secondary = RecallBundle()
        attempts = []

        async def emit(event_type: str, **payload: Any) -> None:
            if on_event is not None:
                await on_event({"type": event_type, **payload})

        async def generate(hits, purpose: str, repair: str | None = None):
            messages = build_messages(
                character=character,
                history=history,
                user_input=user_input,
                recalled=hits,
                summary=summary,
                repair=repair,
                max_prompt_bytes=self.max_prompt_bytes,
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
            result = self.guardian.validate(text, character)
            attempts.append(
                {"purpose": purpose, "text": text, "guardian": result.model_dump()}
            )
            return text, result

        try:
            async with asyncio.timeout(self.timeout):
                await emit("phase", phase="generating")
                draft, guardian = await generate(primary.hits, "initial")
                text = draft
                await emit("phase", phase="checking")
                if draft:
                    secondary = self.recall.recall(
                        draft,
                        memories,
                        exclude_ids={hit.memory.id for hit in primary.hits},
                    )
                hits = [*primary.hits, *secondary.hits]
                if secondary.hits:
                    await emit("phase", phase="secondary_recall")
                    text, guardian = await generate(hits, "secondary_recall")
                    await emit("phase", phase="checking")
                repaired = not guardian.passed
                if repaired:
                    await emit("phase", phase="repairing")
                    repair = "; ".join(
                        f"{f.category}: {f.reason}" for f in guardian.findings
                    )
                    text, guardian = await generate(hits, "quality_repair", repair)
                    await emit("phase", phase="checking")
        except TimeoutError as exc:
            raise ProviderError("generation timed out") from exc
        metadata = {
            "provider": provider.id,
            "model": model,
            "generation_id": generation_id,
            "attempts": attempts,
        }
        if not guardian.passed:
            evaluation_id = self.storage.save_evaluation(
                conversation_id, draft, "", guardian, metadata
            )
            raise QualityRejected(evaluation_id, guardian)
        if conversation is not None:
            self.storage.commit_turn(
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
        else:
            self.storage.save_evaluation(None, draft, text, guardian, metadata)
        return ChatRunResult(
            text=text,
            draft=draft,
            primary_recall=primary,
            secondary_recall=secondary,
            guardian=guardian,
            regenerated_for_recall=bool(secondary.hits),
            repaired=repaired,
        )
