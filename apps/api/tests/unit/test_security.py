"""API key format (``lmk_<prefix>_<secret>``), password hashing, and session tokens."""

from __future__ import annotations

import uuid

from logmind.core.security import (
    API_KEY_PREFIX,
    decode_session,
    generate_api_key,
    hash_key_secret,
    hash_password,
    issue_session,
    key_display,
    parse_api_key,
    password_problems,
    verify_password,
)


def test_generated_key_has_the_lmk_prefix_shape() -> None:
    key = generate_api_key("pepper")
    assert key.plaintext.startswith(f"{API_KEY_PREFIX}_")
    parts = key.plaintext.split("_", 2)
    assert len(parts) == 3
    assert parts[1] == key.prefix
    assert len(key.prefix) == 12


def test_parse_api_key_round_trips() -> None:
    key = generate_api_key("pepper")
    parsed = parse_api_key(key.plaintext)
    assert parsed is not None
    prefix, secret = parsed
    assert prefix == key.prefix
    assert hash_key_secret(secret, "pepper") == key.secret_hash


def test_parse_api_key_rejects_malformed_input() -> None:
    assert parse_api_key("not-a-key") is None
    assert parse_api_key("lmk_short_x") is None
    assert parse_api_key("wrong_prefix_" + "a" * 12 + "_secret") is None


def test_key_display_never_contains_the_secret() -> None:
    key = generate_api_key("pepper")
    display = key_display(key.prefix)
    assert key.prefix in display
    assert "****" in display


def test_password_hash_and_verify_round_trip() -> None:
    hashed = hash_password("S3curePass1")
    assert verify_password("S3curePass1", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_password_handles_none_hash_safely() -> None:
    assert verify_password("anything", None) is False


def test_password_problems_flags_weak_passwords() -> None:
    assert password_problems("short1A") != []
    assert password_problems("alllowercase1") != []
    assert password_problems("ValidPass123") == []


SECRET_A = "test-only-session-secret-with-32-plus-bytes"
SECRET_B = "another-test-only-secret-with-32-plus-bytes"


def test_session_round_trips_claims() -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token = issue_session(user_id, org_id, "owner", 0, SECRET_A, 12)
    claims = decode_session(token, SECRET_A)
    assert claims is not None
    assert claims.user_id == user_id
    assert claims.org_id == org_id
    assert claims.role == "owner"


def test_session_rejects_wrong_secret() -> None:
    token = issue_session(uuid.uuid4(), uuid.uuid4(), "owner", 0, SECRET_A, 12)
    assert decode_session(token, SECRET_B) is None
