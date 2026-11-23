"""The PII and secret recognizers applied to log content at ingestion (A7).

Adapted from Euron Open PIIShield's recognizer table, keeping only the recognizers that
hold up on plain-text log lines. Logs are dense with timestamps, request ids, order
numbers, durations, ports and version strings, so PIIShield's low-confidence document
recognizers (passport-like codes, bare digit runs as bank accounts, dates of birth, street
addresses, honorific names) are left out: on logs they would redact the very values an
investigation needs. Checksummed recognizers (cards, Aadhaar, IBAN) only fire when the
checksum passes, so an order id is never mistaken for a card number.

Overlap resolution is first claim wins in list order, highest signal first, exactly as in
PIIShield: once a span is claimed, no later recognizer may claim text overlapping it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from re import Match

from logmind.redaction.checksums import iban_ok, luhn_ok, us_ssn_ok, verhoeff_ok

# Every category a project can switch on or off. ip_address is off by default: client
# addresses are usually wanted in logs, but some deployments must not keep them.
CATEGORIES = (
    "credential",
    "email",
    "payment_card",
    "government_id",
    "phone",
    "bank_account",
    "ip_address",
)

Validator = Callable[[Match[str]], bool]


@dataclass(frozen=True, slots=True)
class Recognizer:
    name: str
    category: str
    pattern: re.Pattern[str]
    validate: Validator | None = None
    # The capture group holding the sensitive value, when the match also carries a
    # label that should stay readable (``password=`` keeps its key, loses its value).
    group: int = 0


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _card(m: Match[str]) -> bool:
    digits = _digits(m.group(0))
    return 13 <= len(digits) <= 19 and luhn_ok(digits)


def _aadhaar(m: Match[str]) -> bool:
    digits = _digits(m.group(0))
    return len(digits) == 12 and verhoeff_ok(digits)


def _ssn(m: Match[str]) -> bool:
    return us_ssn_ok(m.group(1), m.group(2), m.group(3))


def _iban(m: Match[str]) -> bool:
    return iban_ok(m.group(0))


def _phone(m: Match[str]) -> bool:
    return 10 <= len(_digits(m.group(0))) <= 15


RECOGNIZERS: list[Recognizer] = [
    Recognizer(
        "private_key",
        "credential",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{16,}?-----END [A-Z ]*PRIVATE KEY-----"
        ),
    ),
    Recognizer("jwt", "credential", re.compile(r"\beyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]{8,}")),
    Recognizer(
        "provider_key",
        "credential",
        re.compile(
            r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"
            r"|\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"
            r"|\bgh[pousr]_[A-Za-z0-9]{36,}"
            r"|\bAIza[0-9A-Za-z_-]{35}"
            r"|\bxox[abposr]-[A-Za-z0-9-]{10,}"
            r"|\blmk_[0-9a-f]{12}_[A-Za-z0-9_-]{20,}"
        ),
    ),
    Recognizer(
        "bearer_token",
        "credential",
        re.compile(r"(?i)\b(?:bearer|basic)\s+([A-Za-z0-9._~+/=-]{16,})"),
        group=1,
    ),
    Recognizer(
        "url_password",
        "credential",
        re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://[^\s:/@]{1,64}:([^\s@/]{3,128})@"),
        group=1,
    ),
    Recognizer(
        "secret_assignment",
        "credential",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token"
            r"|client[_-]?secret)\b[\"']?\s*[:=]\s*[\"']?([^\s\"',;&}]{4,})"
        ),
        group=1,
    ),
    Recognizer(
        "email",
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}\b"),
    ),
    Recognizer(
        "payment_card",
        "payment_card",
        re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])"),
        _card,
    ),
    Recognizer(
        "iban",
        "bank_account",
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"),
        _iban,
    ),
    Recognizer("us_ssn", "government_id", re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b"), _ssn),
    Recognizer(
        "aadhaar",
        "government_id",
        re.compile(r"(?<![\d.:-])[2-9]\d{3}[ -]\d{4}[ -]\d{4}(?![\d.:-])"),
        _aadhaar,
    ),
    # Phone numbers only in an unmistakable written form (an international prefix or a
    # bracketed area code): bare 10-digit runs in logs are ids far more often than phones.
    Recognizer(
        "phone",
        "phone",
        re.compile(
            r"(?<![\w+])\+\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]?\d{3,4}[ .-]?\d{3,4}(?!\d)"
            r"|(?<![\w(])\(\d{3}\)\s?\d{3}[ .-]\d{4}(?!\d)"
        ),
        _phone,
    ),
    Recognizer(
        "ipv4",
        "ip_address",
        re.compile(
            r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"
        ),
    ),
]

# Attribute keys whose whole value is a credential, whatever it looks like.
SENSITIVE_KEYS = re.compile(
    r"(?i)^(?:password|passwd|pwd|secret|client_secret|api[_-]?key|token|access_token|"
    r"refresh_token|auth(?:orization)?|cookie|set-cookie|x-api-key|private_key)$"
)
