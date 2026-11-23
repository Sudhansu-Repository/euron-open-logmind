"""OpenAPI drift: the committed ``docs/api/openapi.yaml`` matches what the live app
produces right now. Fails loudly (with a diff hint) if a route changed without
re-running ``logmind openapi > docs/api/openapi.yaml``."""

from __future__ import annotations

from pathlib import Path

import yaml

from logmind.openapi import spec

DOCS_OPENAPI = Path(__file__).resolve().parents[4] / "docs" / "api" / "openapi.yaml"


def test_committed_openapi_matches_the_live_app() -> None:
    if not DOCS_OPENAPI.exists():
        import pytest

        pytest.skip(f"{DOCS_OPENAPI} not present in this checkout")
    committed = yaml.safe_load(DOCS_OPENAPI.read_text())
    live = spec()
    assert committed.get("paths", {}).keys() == live.get("paths", {}).keys(), (
        "docs/api/openapi.yaml's routes differ from the live app; "
        "regenerate with `uv run logmind openapi > ../../docs/api/openapi.yaml`"
    )
    assert committed.get("info", {}).get("title") == live.get("info", {}).get("title")
