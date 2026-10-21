"""Shared outcome values for committed agent-hood publication."""

from __future__ import annotations

from dataclasses import dataclass


REPOSITORY_FAILURE_SCOPE = "repository"
HOOD_FAILURE_SCOPE = "hood"


@dataclass(frozen=True, slots=True)
class CommitPublicationOutcome:
    published: bool = False
    queued: bool = False
    drained: int = 0
    quarantined: int = 0
    retired: int = 0
    skip_reason: str | None = None
    error: str | None = None
