"""Shared value types for durable agent holds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AgentHoldServiceError(RuntimeError):
    """Raised when a CLI/directive-facing hold action can't resolve its context."""


@dataclass(frozen=True)
class PendingCapture:
    """WAITING/QUEUED artifact dirs frozen as a ``pending`` selector at arm time."""

    artifact_dirs: tuple[str, ...]
    waiting_count: int
    queued_count: int
    skipped_running_count: int


@dataclass(frozen=True)
class AgentHoldArmResult:
    """The armed record plus the pending snapshot that produced its selectors."""

    record: dict[str, Any]
    capture: PendingCapture | None
