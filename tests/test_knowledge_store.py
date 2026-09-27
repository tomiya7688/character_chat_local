import pytest

from character_chat_local.knowledge_store import KnowledgeDictionary
from character_chat_local.models import (
    AliasCandidate,
    CharacterCore,
    ChatMessage,
    EntityCandidate,
    EventCandidate,
    FactCandidate,
    KnowledgeExtractionResult,
    RelationCandidate,
)
from character_chat_local.storage import Storage


def setup_sources(tmp_path):
    storage = Storage(tmp_path / "knowledge.db")
    character = CharacterCore(name="ミカ")
    storage.save_character(character)
    conversation = storage.create_conversation(character.id)
    user_id = storage.add_message(
        conversation, ChatMessage(role="user", content="knowledge source")
    )
    assistant_id = storage.add_message(
        conversation,
        ChatMessage(role="assistant", content="final reply"),
        "fake",
        "small",
    )
    return storage, character, conversation, user_id, assistant_id


def test_alias_canonicalization_and_forward_reverse_lookup(tmp_path):
    storage, character, conversation, user_id, assistant_id = setup_sources(tmp_path)
    dictionary = KnowledgeDictionary(storage)
    extraction = KnowledgeExtractionResult(
        strategy="deterministic-v1",
        entities=[
            EntityCandidate(
                name="りんご",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.95,
            )
        ],
        aliases=[
            AliasCandidate(
                entity="りんご",
                alias="apple",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.95,
            )
        ],
        facts=[
            FactCandidate(
                subject="りんご",
                predicate="taste",
                value="甘い",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.95,
            )
        ],
        relations=[
            RelationCandidate(
                subject="りんご",
                predicate="has_property",
                object="甘い",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.9,
            )
        ],
    )

    result = dictionary.promote(
        character_id=character.id,
        extraction=extraction,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    assert result.entities_created >= 2
    assert result.aliases_created == 1
    assert result.records_created == 1
    assert result.relations_created == 1

    owner_id = result.owner_id
    canonical = dictionary.find_entity(owner_id, "APPLE")
    assert canonical is not None
    assert canonical.canonical_name == "りんご"

    forward = dictionary.lookup_relations(owner_id, "りんご")
    assert len(forward) == 1
    assert forward[0].direction == "forward"
    assert forward[0].effective_relation_type == "has_property"
    assert forward[0].object == "甘い"

    reverse = dictionary.lookup_relations(owner_id, "甘い")
    assert len(reverse) == 1
    assert reverse[0].direction == "reverse"
    assert reverse[0].effective_relation_type == "property_of"
    assert reverse[0].subject == "りんご"

    by_value = dictionary.lookup_records(owner_id, "甘い")
    assert len(by_value) == 1
    assert by_value[0].matched_on == "value"
    assert by_value[0].subject == "りんご"


def test_fact_dedupe_supersede_and_non_destructive_history(tmp_path):
    storage, character, conversation, user_id, assistant_id = setup_sources(tmp_path)
    dictionary = KnowledgeDictionary(storage)

    first = KnowledgeExtractionResult(
        strategy="deterministic-v1",
        facts=[
            FactCandidate(
                subject="ミカ",
                predicate="location",
                value="東京",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.9,
            )
        ],
    )
    promoted = dictionary.promote(
        character_id=character.id,
        extraction=first,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    assert promoted.records_created == 1

    duplicate = dictionary.promote(
        character_id=character.id,
        extraction=first,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    assert duplicate.records_created == 0
    assert duplicate.records_merged == 1

    second = KnowledgeExtractionResult(
        strategy="deterministic-v1",
        facts=[
            FactCandidate(
                subject="ミカ",
                predicate="location",
                value="大阪",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.95,
            )
        ],
    )
    updated = dictionary.promote(
        character_id=character.id,
        extraction=second,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    assert updated.records_created == 1
    assert updated.records_superseded == 1

    history = dictionary.record_history(updated.owner_id, "ミカ", "location")
    assert len(history) == 2
    assert history[0].value == "東京"
    assert history[0].status == "superseded"
    assert history[0].superseded_by == history[1].id
    assert history[0].valid_to is not None
    assert history[1].value == "大阪"
    assert history[1].status == "active"

    invalidated = dictionary.invalidate_record(history[1].id)
    assert invalidated.status == "invalidated"
    assert invalidated.invalidated_at is not None
    assert len(dictionary.record_history(updated.owner_id, "ミカ", "location")) == 2


def test_assistant_claim_does_not_supersede_user_fact(tmp_path):
    storage, character, conversation, user_id, assistant_id = setup_sources(tmp_path)
    dictionary = KnowledgeDictionary(storage)
    user_fact = KnowledgeExtractionResult(
        strategy="deterministic-v1",
        facts=[
            FactCandidate(
                subject="user",
                predicate="location",
                value="名古屋",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.95,
            )
        ],
    )
    first = dictionary.promote(
        character_id=character.id,
        extraction=user_fact,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    assistant_claim = KnowledgeExtractionResult(
        strategy="model-v1",
        facts=[
            FactCandidate(
                subject="user",
                predicate="location",
                value="京都",
                source_role="assistant",
                epistemic_state="confirmed",
                confidence=0.9,
            )
        ],
    )
    second = dictionary.promote(
        character_id=character.id,
        extraction=assistant_claim,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )

    history = dictionary.record_history(first.owner_id, "user", "location")
    assert len(history) == 2
    fact = next(item for item in history if item.value == "名古屋")
    claim = next(item for item in history if item.value == "京都")
    assert fact.status == "active"
    assert fact.record_type == "FACT"
    assert claim.status == "active"
    assert claim.record_type == "CLAIM"
    assert claim.epistemic_state == "inferred"
    assert claim.confidence <= 0.65
    assert second.records_superseded == 0


def test_future_event_is_plan_not_fact(tmp_path):
    storage, character, conversation, user_id, assistant_id = setup_sources(tmp_path)
    dictionary = KnowledgeDictionary(storage)
    extraction = KnowledgeExtractionResult(
        strategy="deterministic-v1",
        events=[
            EventCandidate(
                description="明日、東京へ行く予定",
                time_reference="明日",
                entities=["user", "東京"],
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.9,
            )
        ],
    )
    promoted = dictionary.promote(
        character_id=character.id,
        extraction=extraction,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    records = dictionary.active_records(promoted.owner_id)
    assert len(records) == 1
    assert records[0].record_type == "PLAN"
    assert records[0].temporal_context == "planned"
    assert records[0].valid_from is None


def test_provenance_accumulates_without_duplicate_record(tmp_path):
    storage, character, conversation, user_id, assistant_id = setup_sources(tmp_path)
    dictionary = KnowledgeDictionary(storage)
    extraction = KnowledgeExtractionResult(
        strategy="deterministic-v1",
        facts=[
            FactCandidate(
                subject="user",
                predicate="age",
                value="20",
                source_role="user",
                epistemic_state="confirmed",
                confidence=0.9,
            )
        ],
    )
    promoted = dictionary.promote(
        character_id=character.id,
        extraction=extraction,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    second_user = storage.add_message(
        conversation, ChatMessage(role="user", content="again")
    )
    dictionary.promote(
        character_id=character.id,
        extraction=extraction,
        conversation_id=conversation,
        user_message_id=second_user,
        assistant_message_id=assistant_id,
    )

    record = dictionary.active_records(promoted.owner_id)[0]
    sources = dictionary.provenance("record", record.id)
    assert {item.source_message_id for item in sources} == {user_id, second_user}


def test_knowledge_owners_are_isolated_by_owner_and_timeline(tmp_path):
    storage = Storage(tmp_path / "owners.db")
    dictionary = KnowledgeDictionary(storage)

    world = dictionary.get_or_create_owner("world")
    user = dictionary.get_or_create_owner("user")
    character_main = dictionary.get_or_create_owner(
        "character", character_id="character-1", timeline_id="main"
    )
    character_alt = dictionary.get_or_create_owner(
        "character", character_id="character-1", timeline_id="alternate"
    )

    assert len({world.id, user.id, character_main.id, character_alt.id}) == 4
    assert character_main.timeline_id == "main"
    assert character_alt.timeline_id == "alternate"
    assert (
        dictionary.find_owner("character", character_id="character-1").id
        == character_main.id
    )


@pytest.mark.parametrize(
    ("value", "epistemic", "source_role", "expected"),
    [
        ("映画を見たい", "confirmed", "user", "INTENT"),
        ("明日は雨だろう", "confirmed", "user", "PREDICTION"),
        ("明日映画を見る予定", "confirmed", "user", "PLAN"),
        ("たぶん猫が好き", "inferred", "user", "INFERENCE"),
        ("猫が好きかもしれない", "hypothesis", "user", "PREDICTION"),
        ("昔京都へ行った", "confirmed", "assistant", "CLAIM"),
    ],
)
def test_epistemic_record_types_do_not_auto_promote_to_fact(
    tmp_path, value, epistemic, source_role, expected
):
    storage, character, conversation, user_id, assistant_id = setup_sources(tmp_path)
    dictionary = KnowledgeDictionary(storage)
    extraction = KnowledgeExtractionResult(
        strategy="model-v1",
        facts=[
            FactCandidate(
                subject="user",
                predicate="note",
                value=value,
                source_role=source_role,
                epistemic_state=epistemic,
                confidence=0.9,
            )
        ],
    )
    promoted = dictionary.promote(
        character_id=character.id,
        extraction=extraction,
        conversation_id=conversation,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
    )
    record = dictionary.active_records(promoted.owner_id)[0]
    assert record.record_type == expected
    if source_role == "assistant":
        assert record.epistemic_state == "inferred"
        assert record.confidence <= 0.65
