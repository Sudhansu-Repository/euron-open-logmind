"""Unit tests: pure logic, no database, no network."""

from __future__ import annotations

import pytest

from logmind.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test")
