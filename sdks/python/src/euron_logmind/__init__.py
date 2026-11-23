"""Python SDK for Euron Open LogMind: ship structured log lines to a self-hosted LogMind.

from euron_logmind import LogMind

log = LogMind(api_key="lmk_...", service="checkout")
log.info("order placed", order_id=42)
try:
    charge()
except Exception:
    log.exception("charge failed")
"""

from euron_logmind._version import __version__
from euron_logmind.client import DEFAULT_ENDPOINT, LogMind
from euron_logmind.errors import IngestError, LogMindError
from euron_logmind.handler import LogMindHandler
from euron_logmind.models import LEVELS, IngestResult, RejectedLine, Stats

__all__ = [
    "DEFAULT_ENDPOINT",
    "LEVELS",
    "IngestError",
    "IngestResult",
    "LogMind",
    "LogMindError",
    "LogMindHandler",
    "RejectedLine",
    "Stats",
    "__version__",
]
