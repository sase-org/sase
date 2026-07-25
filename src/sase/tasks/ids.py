"""Generation and unique-prefix resolution for background-task ids."""

from __future__ import annotations

import secrets
from collections.abc import Sequence

from .models import BackgroundTask

TASK_ID_LENGTH = 12
SHORT_TASK_ID_LENGTH = 6
MIN_TASK_REF_LENGTH = 3
TASK_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


class TaskRefError(ValueError):
    """A task reference was too short, unknown, or ambiguous."""


def new_task_id() -> str:
    """Mint a 12-character lowercase unambiguous base32 task id."""
    return "".join(secrets.choice(TASK_ID_ALPHABET) for _ in range(TASK_ID_LENGTH))


def short_task_id(task_id: str) -> str:
    """Return the standard six-character task-id display prefix."""
    return task_id[:SHORT_TASK_ID_LENGTH]


def resolve_task_ref(prefix: str, tasks: Sequence[BackgroundTask]) -> BackgroundTask:
    """Resolve a unique task-id prefix of at least three characters."""
    ref = prefix.strip().lower()
    if len(ref) < MIN_TASK_REF_LENGTH:
        raise TaskRefError(
            f"task reference must be at least {MIN_TASK_REF_LENGTH} characters"
        )
    matches = [task for task in tasks if task.task_id.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise TaskRefError(f"no task matches reference {prefix!r}")
    candidates = ", ".join(
        f"{short_task_id(task.task_id)} ({task.label})" for task in matches
    )
    raise TaskRefError(
        f"task reference {prefix!r} is ambiguous; candidates: {candidates}"
    )


__all__ = [
    "MIN_TASK_REF_LENGTH",
    "SHORT_TASK_ID_LENGTH",
    "TASK_ID_ALPHABET",
    "TASK_ID_LENGTH",
    "TaskRefError",
    "new_task_id",
    "resolve_task_ref",
    "short_task_id",
]
