"""Shared types for the :mod:`sase.bead.project` facade."""

from __future__ import annotations

from dataclasses import dataclass

from sase.bead.model import Status


class AlreadyReadyError(Exception):
    """Raised when an epic plan is already marked is_ready_to_work."""


class NotAPlanError(Exception):
    """Raised when mark_ready_to_work is called on a non-plan issue."""


@dataclass(frozen=True)
class EpicPreclaimRollback:
    """Prior bead state returned by one atomic epic-work preclaim."""

    bead_id: str
    status: Status
    assignee: str
