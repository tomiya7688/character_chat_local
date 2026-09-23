from character_chat_local.models import MemoryRecord
from character_chat_local.recall import RecallEngine


def test_trigger_recall():
    memory = MemoryRecord(
        character_id="c1",
        type="episodic",
        content="雨の日に古い事故を思い出す",
        triggers=["雨", "事故"],
        importance=0.9,
    )
    result = RecallEngine().recall("今日は雨だね", [memory])
    assert result.hits
    assert result.hits[0].memory.id == memory.id


def test_excluded_memory_is_not_returned():
    memory = MemoryRecord(
        character_id="c1",
        type="canon",
        content="猫が好き",
        triggers=["猫"],
    )
    result = RecallEngine().recall("猫の話", [memory], exclude_ids={memory.id})
    assert result.hits == []
