from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class GuardrailResult:
    safe: bool
    reason: str


class InputGuardrails:
    _INJECTION_PATTERNS = [
        r"ignore\s+previous",
        r"forget\s+instructions",
        r"you\s+are\s+now",
        r"jailbreak",
        r"act\s+as",
    ]

    _TOPIC_HINTS = [
        "document",
        "pdf",
        "section",
        "table",
        "page",
        "return",
        "vat",
        "comply",
        "policy",
        "invoice",
    ]

    def validate(self, query: str) -> GuardrailResult:
        cleaned = query.strip().lower()
        if not cleaned:
            return GuardrailResult(False, "Empty query")

        for pattern in self._INJECTION_PATTERNS:
            if re.search(pattern, cleaned):
                return GuardrailResult(False, "Prompt injection pattern detected")

        if not any(hint in cleaned for hint in self._TOPIC_HINTS):
            return GuardrailResult(False, "Query appears off-topic for the document corpus")

        return GuardrailResult(True, "ok")
