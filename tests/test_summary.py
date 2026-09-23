from character_chat_local.models import ConversationSummary, StoredMessage
from character_chat_local.summary import SummaryEngine


def test_large_legacy_history_is_compacted_incrementally():
    def rows():
        for i in range(10000):
            yield StoredMessage(
                id=f"m{i}",
                position=i + 1,
                role="user" if i % 2 == 0 else "assistant",
                content="私の名前はカドカ" if i == 0 else f"発言{i}",
            )

    summary, recent = SummaryEngine().prepare(ConversationSummary(), rows())
    assert summary.covered_messages == summary.through_position == 9988
    assert len(recent) == 12 and len(summary.entries) <= 12
    assert summary.entries[0].source_message_id == "m0"
    assert "カドカ" in summary.entries[0].excerpt
    assert all(len(entry.excerpt) <= 160 for entry in summary.entries)


def test_preparation_does_not_mutate_saved_summary():
    saved = ConversationSummary()
    summary, _ = SummaryEngine().prepare(
        saved,
        (
            StoredMessage(
                id=str(i),
                position=i + 1,
                role="user" if i % 2 == 0 else "assistant",
                content="会話",
            )
            for i in range(20)
        ),
    )
    assert saved.covered_messages == 0 and saved.entries == []
    assert summary.covered_messages == 8
