from __future__ import annotations

import re
from collections.abc import Iterable

from .models import InputAnalysisResult

_QUOTED_RE = re.compile(
    r"「([^」]{1,40})」|『([^』]{1,40})』|\"([^\"\n]{1,40})\"|'([^'\n]{1,40})'"
)
_HASHTAG_RE = re.compile(r"(?<!\w)[#@]([A-Za-z0-9_\-]{2,40})")
_LATIN_ENTITY_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9_\-]{1,30})(?:\s+[A-Z][A-Za-z0-9_\-]{1,30})*\b")
_PERSON_RE = re.compile(
    r"([一-龠々ぁ-んァ-ヶA-Za-z][一-龠々ぁ-んァ-ヶA-Za-z0-9_]{0,20})"
    r"(さん|ちゃん|くん|君|様|先生|先輩)"
)
_PLACE_RE = re.compile(
    r"([一-龠々ぁ-んァ-ヶA-Za-z][一-龠々ぁ-んァ-ヶA-Za-z0-9_]{0,24})"
    r"(都|道|府|県|市|区|町|村|駅|公園|学校|大学|病院|空港|港|海|山|川|湖|店|カフェ|レストラン)"
)
_TIME_RE = re.compile(
    r"(今日|明日|昨日|一昨日|明後日|今朝|今夜|今晩|今週|来週|先週|"
    r"今月|来月|先月|今年|来年|去年|さっき|あとで|後で|これから|"
    r"today|tomorrow|yesterday|tonight|this week|next week|last week|"
    r"\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|"
    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{1,2}:\d{2})",
    re.IGNORECASE,
)

_EMOTION_LEXICON: dict[str, tuple[str, ...]] = {
    "joy": ("嬉しい", "楽しい", "幸せ", "うれしい", "たのしい", "happy", "glad", "excited"),
    "sadness": ("悲しい", "寂しい", "つらい", "かなしい", "sad", "lonely"),
    "anger": ("怒り", "怒って", "腹が立", "むかつ", "angry", "mad"),
    "fear": ("怖い", "こわい", "恐い", "fear", "scared", "afraid"),
    "anxiety": ("不安", "心配", "緊張", "anxious", "worried", "nervous"),
    "affection": ("好き", "大好き", "愛して", "love", "like you"),
    "surprise": ("驚", "びっくり", "surprised", "wow"),
}

_MEMORY_MARKERS = (
    "覚えて",
    "忘れないで",
    "記憶して",
    "メモして",
    "remember",
    "don't forget",
    "do not forget",
    "keep this in mind",
)
_GREETING_MARKERS = (
    "こんにちは",
    "おはよう",
    "こんばんは",
    "やあ",
    "hello",
    "hi ",
    "hey",
)
_REQUEST_MARKERS = (
    "してください",
    "してほしい",
    "お願い",
    "教えて",
    "見せて",
    "please",
    "could you",
    "can you",
)
_PLAN_MARKERS = ("しよう", "行こう", "やろう", "let's", "lets ")
_TOPIC_SPLIT_RE = re.compile(
    r"(?:について|という|って|から|まで|より|では|には|へは|とは|"
    r"[、。！？!?\n\t]|\s{2,}|[はがをにへでとも])"
)
_TOPIC_STOP = {
    "これ",
    "それ",
    "あれ",
    "ここ",
    "そこ",
    "今日",
    "明日",
    "昨日",
    "私",
    "僕",
    "俺",
    "あなた",
    "君",
    "please",
    "the",
    "this",
    "that",
}


def _unique(values: Iterable[str], limit: int = 12) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip(" 、。！？!?.,:;()[]{}")
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _suffix_value(raw: str) -> str:
    parts = re.split(r"[はがをにへでとのも、。！？!?\s]", raw)
    value = parts[-1].strip() if parts else raw.strip()
    return value or raw.strip()


class InputAnalyzer:
    """Deterministic, model-free input analysis used before recall."""

    def analyze(
        self,
        text: str,
        *,
        known_entities: Iterable[str] = (),
        known_people: Iterable[str] = (),
        known_places: Iterable[str] = (),
    ) -> InputAnalysisResult:
        folded = text.casefold()

        quoted: list[str] = []
        for match in _QUOTED_RE.finditer(text):
            quoted.extend(group for group in match.groups() if group)

        known_entity_hits = [
            value for value in known_entities if value.strip() and value.casefold() in folded
        ]
        known_people_hits = [
            value for value in known_people if value.strip() and value.casefold() in folded
        ]
        known_place_hits = [
            value for value in known_places if value.strip() and value.casefold() in folded
        ]

        people = [
            _suffix_value(match.group(1))
            for match in _PERSON_RE.finditer(text)
        ]
        people.extend(known_people_hits)

        places = [
            _suffix_value(match.group(1)) + match.group(2)
            for match in _PLACE_RE.finditer(text)
        ]
        places.extend(known_place_hits)

        entities = [*quoted]
        entities.extend(match.group(1) for match in _HASHTAG_RE.finditer(text))
        entities.extend(match.group(0) for match in _LATIN_ENTITY_RE.finditer(text))
        entities.extend(known_entity_hits)
        entities.extend(people)
        entities.extend(places)

        emotions = [
            label
            for label, markers in _EMOTION_LEXICON.items()
            if any(marker.casefold() in folded for marker in markers)
        ]

        explicit_memory_request = any(
            marker.casefold() in folded for marker in _MEMORY_MARKERS
        )
        intents: list[str] = []
        if explicit_memory_request:
            intents.append("memory_request")
        if "?" in text or "？" in text or re.search(r"(ですか|ますか|かな|か)$", text.strip()):
            intents.append("question")
        if any(marker.casefold() in folded for marker in _REQUEST_MARKERS):
            intents.append("request")
        if any(marker.casefold() in folded for marker in _PLAN_MARKERS):
            intents.append("plan")
        if any(marker.casefold() in folded for marker in _GREETING_MARKERS):
            intents.append("greeting")
        if not intents:
            intents.append("statement")

        time_references = [match.group(0) for match in _TIME_RE.finditer(text)]

        topic_candidates: list[str] = [*quoted, *known_entity_hits]
        for chunk in _TOPIC_SPLIT_RE.split(text):
            cleaned = chunk.strip(" 、。！？!?.,:;()[]{}\"'")
            if not 2 <= len(cleaned) <= 32:
                continue
            if cleaned.casefold() in _TOPIC_STOP:
                continue
            if any(cleaned.casefold() == value.casefold() for value in time_references):
                continue
            topic_candidates.append(cleaned)

        return InputAnalysisResult(
            topics=_unique(topic_candidates, 10),
            entities=_unique(entities, 12),
            people=_unique(people, 8),
            places=_unique(places, 8),
            emotions=_unique(emotions, 8),
            intents=_unique(intents, 8),
            time_references=_unique(time_references, 8),
            explicit_memory_request=explicit_memory_request,
        )
