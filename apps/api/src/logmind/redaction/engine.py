"""Apply a project's redaction policy to one log event before it is stored (A7).

The policy is the set of enabled categories, the project's own extra patterns and the
mode: ``mask`` replaces a value with ``[REDACTED:<category>]``; ``hash`` with
``[<category>:<8 hex>]``, a keyed hash so the same email in two lines still correlates
without being readable. Messages, stack traces and every string value inside the
attributes (keys kept, nested objects walked) are covered. Redaction runs in the request,
before the ClickHouse insert and before the live stream publish, so an unredacted value is
never written anywhere, not even to a queue.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from logmind.redaction.recognizers import RECOGNIZERS, SENSITIVE_KEYS, Recognizer

# Bounds the work one value can cost; anything longer is truncated earlier at ingestion.
MAX_SCAN_CHARS = 64_000
MAX_DEPTH = 8


@dataclass(frozen=True, slots=True)
class CustomPattern:
    name: str
    pattern: re.Pattern[str]


@dataclass(slots=True)
class RedactionResult:
    counts: Counter[str] = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class Redactor:
    """Built once per project policy (cached with the project config), then reused for
    every event of every batch."""

    def __init__(
        self,
        *,
        enabled: bool,
        categories: list[str],
        custom: list[CustomPattern] | None = None,
        mode: str = "mask",
        hash_key: str = "",
    ) -> None:
        self.enabled = enabled
        wanted = set(categories)
        self._recognizers: list[Recognizer] = [r for r in RECOGNIZERS if r.category in wanted]
        self._custom = custom or []
        self._mode = mode
        self._key = hash_key.encode()
        self._sensitive_keys = "credential" in wanted

    def _replacement(self, category: str, value: str) -> str:
        if self._mode == "hash":
            digest = hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()[:8]
            return f"[{category}:{digest}]"
        return f"[REDACTED:{category}]"

    def redact_text(self, text: str, result: RedactionResult) -> str:
        if not self.enabled or not text:
            return text
        text = text[:MAX_SCAN_CHARS]
        spans: list[tuple[int, int, str]] = []

        def free(start: int, end: int) -> bool:
            return all(e <= start or end <= s for s, e, _ in spans)

        for rec in self._recognizers:
            for m in rec.pattern.finditer(text):
                start, end = m.span(rec.group)
                if start == end or not free(start, end):
                    continue
                if rec.validate is not None and not rec.validate(m):
                    continue
                spans.append((start, end, rec.category))
        for custom in self._custom:
            for m in custom.pattern.finditer(text):
                start, end = m.span()
                if start != end and free(start, end):
                    spans.append((start, end, custom.name))
        if not spans:
            return text
        spans.sort()
        out: list[str] = []
        cursor = 0
        for start, end, category in spans:
            out.append(text[cursor:start])
            out.append(self._replacement(category, text[start:end]))
            result.counts[category] += 1
            cursor = end
        out.append(text[cursor:])
        return "".join(out)

    def redact_value(self, value: Any, result: RedactionResult, depth: int = 0) -> Any:
        if not self.enabled:
            return value
        if depth > MAX_DEPTH:
            return "[truncated]"
        if isinstance(value, str):
            return self.redact_text(value, result)
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                key = str(k)
                if self._sensitive_keys and SENSITIVE_KEYS.match(key) and v not in (None, ""):
                    out[key] = self._replacement("credential", str(v))
                    result.counts["credential"] += 1
                else:
                    out[key] = self.redact_value(v, result, depth + 1)
            return out
        if isinstance(value, list):
            return [self.redact_value(v, result, depth + 1) for v in value]
        return value


def compile_custom(rules: list[dict[str, Any]]) -> list[CustomPattern]:
    """Project custom patterns, validated at the API boundary already; a pattern that no
    longer compiles is skipped rather than failing ingestion."""
    out: list[CustomPattern] = []
    for rule in rules:
        try:
            out.append(CustomPattern(str(rule["name"]), re.compile(str(rule["pattern"]))))
        except (KeyError, re.error):
            continue
    return out
