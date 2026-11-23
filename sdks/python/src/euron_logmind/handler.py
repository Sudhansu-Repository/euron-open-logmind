"""A stdlib :class:`logging.Handler` that forwards records to a :class:`LogMind` client.

    import logging
    from euron_logmind import LogMind, LogMindHandler

    client = LogMind(service="checkout")
    logging.getLogger().addHandler(LogMindHandler(client))
    logging.getLogger("payments").warning("card declined", extra={"order_id": 42})

Mapping: the record's level becomes the LogMind level, ``record.getMessage()`` the
message (``%``-style arguments already applied), ``exc_info`` the structured exception,
``record.created`` the timestamp, and the logger name, module, function, line and thread
go into attributes under ``logger``, ``module``, ``function``, ``line`` and ``thread``.
Every ``extra=`` field becomes an attribute too, except ``trace_id``, ``span_id`` and
``request_id``, which fill the dedicated fields.
"""

from __future__ import annotations

import logging
from typing import Any

from euron_logmind.client import LogMind

# Attributes every LogRecord has; anything else on a record came from ``extra=``.
_RESERVED = frozenset(vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None)).keys()) | {
    "message",
    "asctime",
    "taskName",
}

_PROMOTED = ("trace_id", "span_id", "request_id")

# The SDK's own HTTP stack logs through these; forwarding them would loop forever.
_IGNORED_LOGGERS = ("httpx", "httpcore", "euron_logmind")


class LogMindHandler(logging.Handler):
    """Forward stdlib logging records to LogMind. ``include_location=False`` drops the
    module/function/line/thread attributes for leaner lines."""

    def __init__(
        self, client: LogMind, level: int = logging.NOTSET, *, include_location: bool = True
    ) -> None:
        super().__init__(level)
        self.client = client
        self.include_location = include_location

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.client.is_sender_thread() or record.name.startswith(_IGNORED_LOGGERS):
                return
            attributes: dict[str, Any] = {"logger": record.name}
            if self.include_location:
                attributes.update(
                    module=record.module,
                    function=record.funcName,
                    line=record.lineno,
                    thread=record.threadName,
                )
            promoted: dict[str, str] = {}
            for key, value in vars(record).items():
                if key in _RESERVED or key.startswith("_"):
                    continue
                if key in _PROMOTED and value is not None:
                    promoted[key] = str(value)
                else:
                    attributes[key] = value
            self.client.log(
                record.levelno,
                record.getMessage(),
                attributes=attributes,
                exc_info=record.exc_info,
                timestamp=record.created,
                trace_id=promoted.get("trace_id"),
                span_id=promoted.get("span_id"),
                request_id=promoted.get("request_id"),
            )
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        self.client.flush(timeout=5.0)
