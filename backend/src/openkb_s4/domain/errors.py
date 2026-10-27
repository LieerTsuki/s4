"""Safe domain failures shared by HTTP and worker entry points."""

from __future__ import annotations


class DomainError(ValueError):
    """Reject invalid business input without embedding sensitive source content."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
