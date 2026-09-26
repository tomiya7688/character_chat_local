from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import (
    CharacterCore,
    GuardianFinding,
    LightweightCheckResult,
    MemoryRecord,
)

_META_PHRASES = ("as an ai", "as a language model", "aiとして", "言語モデルとして")
_USER_CONTROL = re.compile(r"あなたは[^。！？\n]{0,30}(?:言った|歩いた|座った|笑った)")
_RELATIONSHIP_SIGNALS = (
    "恋人",
    "結婚",
    "大好き",
    "嫌いになった",
    "親友",
    "永遠",
    "remember",
    "don't forget",
    "promise",
    "relationship",
    "覚えて",
    "忘れないで",
    "約束",
)


def _sentences(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", part).strip().casefold()
        for part in re.split(r"[。.!?！？\n]+", text)
        if part.strip()
    ]


class LightweightDraftChecker:
    """Cheap deterministic gate and escalation signal. No model call."""

    def check(
        self,
        text: str,
        character: CharacterCore,
        *,
        memories: list[MemoryRecord] | None = None,
        recalled_ids: set[str] | None = None,
    ) -> LightweightCheckResult:
        findings: list[GuardianFinding] = []
        signals: list[str] = []
        stripped = text.strip()
        folded = stripped.casefold()

        if not stripped:
            findings.append(
                GuardianFinding(
                    category="formatting_break",
                    severity=1.0,
                    reason="empty response",
                )
            )
        if len(text) > 8000:
            findings.append(
                GuardianFinding(
                    category="formatting_break",
                    severity=1.0,
                    reason="response exceeded output limit",
                )
            )
        if any(phrase in folded for phrase in _META_PHRASES):
            findings.append(
                GuardianFinding(
                    category="meta_leak",
                    severity=0.9,
                    reason="meta phrase detected",
                )
            )
        if _USER_CONTROL.search(text):
            findings.append(
                GuardianFinding(
                    category="user_control",
                    severity=0.8,
                    reason="response appears to decide the user's action",
                )
            )

        sentences = _sentences(text)
        duplicate = len(sentences) >= 3 and len(set(sentences)) < len(sentences)
        near_duplicate = False
        if not duplicate and len(sentences) >= 3:
            for index, left in enumerate(sentences):
                if len(left) < 8:
                    continue
                for right in sentences[index + 1 :]:
                    if (
                        len(right) >= 8
                        and SequenceMatcher(None, left, right).ratio() >= 0.9
                    ):
                        near_duplicate = True
                        break
                if near_duplicate:
                    break
        if duplicate or near_duplicate:
            findings.append(
                GuardianFinding(
                    category="repetition",
                    severity=0.7,
                    reason="duplicate or near-duplicate sentence detected",
                )
            )

        for forbidden in character.forbidden:
            token = forbidden.strip().casefold()
            if token and token in folded:
                findings.append(
                    GuardianFinding(
                        category="character_break",
                        severity=0.9,
                        reason="forbidden character constraint appeared",
                    )
                )

        recalled = recalled_ids or set()
        for memory in memories or []:
            if memory.id in recalled:
                continue
            terms = [
                item.strip().casefold()
                for item in [*memory.triggers, *memory.entities]
                if item.strip()
            ]
            if any(term in folded for term in terms):
                signals.append("unrecalled_memory_signal")
                break

        if any(term in folded for term in _RELATIONSHIP_SIGNALS):
            signals.append("relationship_or_memory_change_signal")

        # Preserve order while keeping the trace compact.
        signals = list(dict.fromkeys(signals))
        hard_fail = any(item.severity >= 0.7 for item in findings)
        return LightweightCheckResult(
            passed=not hard_fail,
            requires_inspection=hard_fail or bool(signals),
            findings=findings,
            inspect_signals=signals,
        )
