from __future__ import annotations

from .models import CharacterCore, ChatMessage, RecallHit


def build_system_prompt(character: CharacterCore, recalled: list[RecallHit]) -> str:
    memory_text = "\n".join(hit.memory.content for hit in recalled)
    return f"Character: {character.name}\n{memory_text}".strip()


def build_messages(
    *,
    character: CharacterCore,
    history: list[ChatMessage],
    user_input: str,
    recalled: list[RecallHit],
) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=build_system_prompt(character, recalled)),
        *history,
        ChatMessage(role="user", content=user_input),
    ]
