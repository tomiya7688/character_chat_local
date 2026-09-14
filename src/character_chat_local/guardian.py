from __future__ import annotations

import re

from .models import CharacterCore, GuardianFinding, GuardianResult

_META_PHRASES = ("as an ai", "as a language model", "aiとして", "言語モデルとして")
_USER_CONTROL = re.compile(r"あなたは[^。！？\n]{0,30}(?:言った|歩いた|座った|笑った)")


class Guardian:
    def validate(self, text: str, character: CharacterCore) -> GuardianResult:
        findings: list[GuardianFinding] = []
        folded = text.casefold()

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

        sentences = [part.strip() for part in re.split(r"[。.!?！？\n]+", text) if part.strip()]
        if len(sentences) >= 3 and len(set(sentences)) < len(sentences):
            findings.append(
                GuardianFinding(
                    category="repetition",
                    severity=0.5,
                    reason="duplicate sentence detected",
                )
            )

        for forbidden in character.forbidden:
            if forbidden and forbidden.casefold() in folded:
                findings.append(
                    GuardianFinding(
                        category="character_break",
                        severity=0.9,
                        reason="forbidden character constraint appeared",
                    )
                )

        passed = not any(finding.severity >= 0.7 for finding in findings)
        return GuardianResult(passed=passed, findings=findings)
