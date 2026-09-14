from __future__ import annotations

from .guardian import Guardian
from .models import CharacterCore, ChatMessage, ChatRunResult
from .prompting import build_messages
from .providers import AIProvider
from .recall import RecallEngine
from .storage import Storage


async def _collect(
    provider: AIProvider,
    model: str,
    messages: list[ChatMessage],
    temperature: float,
) -> str:
    parts = []
    async for part in provider.stream_chat(
        model=model,
        messages=messages,
        temperature=temperature,
    ):
        parts.append(part)
    return "".join(parts).strip()


class ChatService:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.recall = RecallEngine()
        self.guardian = Guardian()

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
    ) -> ChatRunResult:
        history = history or []
        memories = self.storage.list_memories(character.id)
        primary = self.recall.recall(user_input, memories)
        messages = build_messages(
            character=character,
            history=history,
            user_input=user_input,
            recalled=primary.hits,
        )
        draft = await _collect(provider, model, messages, temperature)
        if not draft:
            raise RuntimeError("provider returned an empty response")

        primary_ids = {hit.memory.id for hit in primary.hits}
        secondary = self.recall.recall(draft, memories, exclude_ids=primary_ids)
        regenerated = bool(secondary.hits)
        text = draft
        if regenerated:
            messages = build_messages(
                character=character,
                history=history,
                user_input=user_input,
                recalled=[*primary.hits, *secondary.hits],
            )
            text = await _collect(provider, model, messages, temperature)

        guardian = self.guardian.validate(text, character)
        if conversation_id:
            self.storage.add_message(
                conversation_id,
                ChatMessage(role="user", content=user_input),
            )
            self.storage.add_message(
                conversation_id,
                ChatMessage(role="assistant", content=text),
                provider=provider.id,
                model=model,
            )
        self.storage.save_evaluation(conversation_id, draft, text, guardian)
        return ChatRunResult(
            text=text,
            draft=draft,
            primary_recall=primary,
            secondary_recall=secondary,
            guardian=guardian,
            regenerated_for_recall=regenerated,
            repaired=False,
        )
