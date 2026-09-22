"""Bounded, deterministic extracts; never promote conversation text into Canon."""

from collections.abc import Iterable

from .models import ConversationSummary, StoredMessage, SummaryEntry

_IMPORTANT = (
    "約束", "覚えて", "名前は", "好き", "嫌い", "大切", "苦手",
    "promise", "remember", "my name", "favorite", "allergic",
)


class SummaryEngine:
    def __init__(self, *, recent_messages: int = 12, max_entries: int = 12):
        if recent_messages < 2 or recent_messages % 2 or max_entries < 4:
            raise ValueError("use an even recent window >= 2 and max_entries >= 4")
        self.recent_messages = recent_messages
        self.max_entries = max_entries

    def prepare(
        self,
        summary: ConversationSummary,
        messages: Iterable[StoredMessage],
    ) -> tuple[ConversationSummary, list[StoredMessage]]:
        """Consume the unread suffix in bounded batches, including legacy histories."""
        result = summary.model_copy(deep=True)
        recent: list[StoredMessage] = []
        for message in messages:
            if message.position <= result.through_position:
                continue
            recent.append(message)
            if len(recent) > self.recent_messages + 32:
                self._fold(result, recent[:32])
                del recent[:32]
        count = max(0, len(recent) - self.recent_messages)
        # Retain complete pairs for ordinary persisted user/assistant exchanges.
        count -= count % 2
        if count:
            self._fold(result, recent[:count])
            del recent[:count]
        return result, recent

    def _fold(self, summary: ConversationSummary, messages: list[StoredMessage]) -> None:
        entries = list(summary.entries)
        for message in messages:
            if message.position <= summary.through_position:
                continue
            content = message.content.strip()
            important = message.role == "user" and any(
                word in content.casefold() for word in _IMPORTANT
            )
            entries.append(SummaryEntry(
                source_message_id=message.id,
                position=message.position,
                role=message.role,
                excerpt=content[:160],
                priority=2 if important else int(message.role == "user"),
            ))
            summary.through_position = message.position
            summary.covered_messages += 1
        # Preserve an early anchor, important user statements, and recent extracts.
        anchor = entries[:1]
        recent = entries[-self.max_entries // 2:]
        chosen = {entry.source_message_id: entry for entry in [*anchor, *recent]}
        ranked = sorted(entries, key=lambda e: (e.priority, e.position), reverse=True)
        for entry in ranked:
            if len(chosen) >= self.max_entries:
                break
            chosen.setdefault(entry.source_message_id, entry)
        summary.entries = sorted(chosen.values(), key=lambda e: e.position)
