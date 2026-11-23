from __future__ import annotations

from logmind.core.errors import AppError, ConflictError


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"
    type = "authentication_error"


class EmailTakenError(ConflictError):
    code = "email_taken"


class WeakPasswordError(AppError):
    status_code = 422
    code = "weak_password"
