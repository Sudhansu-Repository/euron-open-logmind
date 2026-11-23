from __future__ import annotations

from logmind.core.errors import AppError


class UnknownProjectError(AppError):
    status_code = 404
    code = "unknown_project"
