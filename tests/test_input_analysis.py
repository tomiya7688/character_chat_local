from character_chat_local.analysis import InputAnalyzer


def test_input_analysis_extracts_required_dimensions_without_llm():
    result = InputAnalyzer().analyze(
        "明日、東京駅で田中さんと「OpenAI」について話そう。少し不安。これ覚えておいて？"
    )

    assert "OpenAI" in result.topics
    assert "OpenAI" in result.entities
    assert "田中" in result.people
    assert "東京駅" in result.places
    assert "anxiety" in result.emotions
    assert "memory_request" in result.intents
    assert "question" in result.intents
    assert "明日" in result.time_references
    assert result.explicit_memory_request
    assert result.strategy == "heuristic-v2"


def test_input_analysis_uses_known_entities_and_has_statement_fallback():
    result = InputAnalyzer().analyze(
        "灯台のことを話す",
        known_entities=["灯台", "港"],
        known_people=["ミカ"],
    )

    assert "灯台" in result.entities
    assert "灯台" in result.topics
    assert result.intents == ["statement"]
    assert not result.explicit_memory_request


def test_input_analysis_is_bounded_and_deduplicated():
    result = InputAnalyzer().analyze(
        "「猫」「猫」「犬」「鳥」「魚」「馬」「牛」「羊」「山羊」「狐」「狸」「熊」「鹿」「兎」"
    )
    assert len(result.entities) <= 12
    assert len(result.topics) <= 10
    assert len(result.entities) == len({item.casefold() for item in result.entities})
