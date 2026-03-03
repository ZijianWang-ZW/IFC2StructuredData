"""Backend-specific exceptions."""

from __future__ import annotations


class EntityNotFoundError(Exception):
    """Raised when a requested entity does not exist."""

