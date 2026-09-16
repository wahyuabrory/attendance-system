from __future__ import annotations


class AppError(Exception):
    """An expected error with a safe public code and message."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class RuntimeConfigError(RuntimeError):
    """Configuration prevents the service from starting."""
