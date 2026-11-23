"""A7 at the unit level: what each category catches, what it must leave alone."""

from __future__ import annotations

import pytest

from logmind.projects.schemas import RedactionCategory
from logmind.redaction.checksums import iban_ok, luhn_ok, us_ssn_ok, verhoeff_ok
from logmind.redaction.engine import RedactionResult, Redactor, compile_custom
from logmind.redaction.recognizers import CATEGORIES

ALL = list(CATEGORIES)


def red(text: str, categories: list[str] | None = None, **kw: object) -> tuple[str, dict[str, int]]:
    r = Redactor(enabled=True, categories=categories or ALL, **kw)  # type: ignore[arg-type]
    result = RedactionResult()
    return r.redact_text(text, result), dict(result.counts)


def test_categories_match_the_api_schema() -> None:
    assert set(RedactionCategory.__args__) == set(CATEGORIES)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("mail jane@example.com now", "email"),
        ("card 4111-1111-1111-1111 ok", "payment_card"),
        ("ssn 123-45-6789", "government_id"),
        ("aadhaar 2345 6789 0124", "government_id"),
        ("iban GB82 WEST 1234 5698 7654 32", "bank_account"),
        ("call +44 20 7946 0958", "phone"),
        ("call (415) 555-0132", "phone"),
        ("from 192.168.10.4", "ip_address"),
        ("key AKIAIOSFODNN7EXAMPLE", "credential"),
        ("token ghp_" + "a" * 36, "credential"),
        ("Authorization: Bearer abcdefghijklmnop1234", "credential"),
        ("postgres://app:s3cretpw@db:5432/x", "credential"),
        ('{"client_secret": "zzz-123-abc"}', "credential"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijkl", "credential"),
        (
            "-----BEGIN "
            + "RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END "
            + "RSA PRIVATE KEY-----",
            "credential",
        ),
    ],
)
def test_each_category(text: str, category: str) -> None:
    out, counts = red(text)
    assert counts.get(category) == 1, (out, counts)
    assert f"[REDACTED:{category}]" in out


@pytest.mark.parametrize(
    "text",
    [
        "order 4000123412341235 shipped",
        "request id 1234567890 took 45ms",
        "ssn-like 000-12-3456",
        "version 1.2.3.4.5 built",
        "trace 4bf92f3577b34da6a3ce929d0e0e4736",
        "2026-11-16T10:00:00Z GET /cart 200",
    ],
)
def test_ordinary_log_values_survive(text: str) -> None:
    out, counts = red(text, [c for c in ALL if c != "ip_address"])
    assert out == text and counts == {}


def test_assignments_keep_the_key_and_hash_mode_correlates() -> None:
    out, _ = red("password=Hunter2Hunter2 user=bob")
    assert out == "password=[REDACTED:credential] user=bob"
    a, _ = red("bob@x.io", ["email"], mode="hash", hash_key="k")
    b, _ = red("bob@x.io", ["email"], mode="hash", hash_key="k")
    c, _ = red("bob@x.io", ["email"], mode="hash", hash_key="other")
    assert a == b != c and a.startswith("[email:")


def test_attributes_are_walked_and_sensitive_keys_masked() -> None:
    r = Redactor(enabled=True, categories=ALL)
    result = RedactionResult()
    out = r.redact_value(
        {
            "user": {"email": "a@b.io", "id": 3},
            "token": "t0k",
            "list": ["x@y.io", 1],
            "deep": {"a": {"b": {}}},
        },
        result,
    )
    assert out == {
        "user": {"email": "[REDACTED:email]", "id": 3},
        "token": "[REDACTED:credential]",
        "list": ["[REDACTED:email]", 1],
        "deep": {"a": {"b": {}}},
    }
    assert result.total == 3
    nested: dict[str, object] = {}
    cur = nested
    for _ in range(12):
        cur["n"] = {}
        cur = cur["n"]  # type: ignore[assignment]
    assert "[truncated]" in str(r.redact_value(nested, result))


def test_disabled_and_custom() -> None:
    off = Redactor(enabled=False, categories=ALL)
    assert off.redact_text("a@b.io", RedactionResult()) == "a@b.io"
    assert off.redact_value({"password": "x"}, RedactionResult()) == {"password": "x"}
    custom = compile_custom(
        [{"name": "emp", "pattern": r"EMP-\d+"}, {"name": "bad", "pattern": "("}, {"x": 1}]
    )
    assert [c.name for c in custom] == ["emp"]
    out, counts = red("id EMP-42", ["email"], custom=custom)
    assert out == "id [REDACTED:emp]" and counts == {"emp": 1}


def test_checksums() -> None:
    assert luhn_ok("4111111111111111") and not luhn_ok("4111111111111112") and not luhn_ok("41x1")
    valid, invalid = "2345" + "67890124", "2345" + "67890123"
    assert verhoeff_ok(valid) and not verhoeff_ok(invalid) and not verhoeff_ok("x")
    assert iban_ok("GB82 WEST 1234 5698 7654 32") and not iban_ok("GB00 WEST 1234 5698 7654 32")
    assert not iban_ok("XX") and not iban_ok("1234567890123456")
    assert us_ssn_ok("123", "45", "6789") and not us_ssn_ok("666", "45", "6789")
