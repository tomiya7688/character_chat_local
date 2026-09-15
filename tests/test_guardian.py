from character_chat_local.guardian import Guardian
from character_chat_local.models import CharacterCore


def test_meta_leak_fails_guardian():
    result = Guardian().validate(
        "AIとして、その質問には答えられます。", CharacterCore(name="A")
    )
    assert not result.passed
    assert any(finding.category == "meta_leak" for finding in result.findings)


def test_clean_response_passes():
    result = Guardian().validate("ふふ、今日は少し静かだね。", CharacterCore(name="A"))
    assert result.passed
