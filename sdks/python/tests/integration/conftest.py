"""Integration fixtures: a real, running LogMind API.

Set ``LOGMIND_TEST_API_URL`` (for example ``http://localhost:6030``) and
``LOGMIND_TEST_API_KEY`` (a project key, ``lmk_<prefix>_<secret>``) to run these tests;
unset, they are skipped (not failed), so ``pytest`` is always safe with no server up.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from euron_logmind import LogMind

URL = os.environ.get("LOGMIND_TEST_API_URL", "")
API_KEY = os.environ.get("LOGMIND_TEST_API_KEY", "")

HERE = os.path.dirname(__file__)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(
        reason="set LOGMIND_TEST_API_URL and LOGMIND_TEST_API_KEY to run the integration tests"
    )
    for item in items:
        if str(item.path).startswith(HERE):
            item.add_marker(pytest.mark.integration)
            if not (URL and API_KEY):
                item.add_marker(skip)


@pytest.fixture
def client() -> Iterator[LogMind]:
    log = LogMind(
        api_key=API_KEY,
        endpoint=URL,
        service="sdk-python-integration",
        environment="test",
        flush_interval_s=0.2,
        register_atexit=False,
    )
    yield log
    log.close(timeout=15)
