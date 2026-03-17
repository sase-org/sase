"""Issue and dependency data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class IssueType(Enum):
    PLAN = "plan"
    PHASE = "phase"


@dataclass
class Dependency:
    issue_id: str
    depends_on_id: str
    created_at: str
    created_by: str = ""


@dataclass
class Issue:
    id: str
    title: str
    status: Status = Status.OPEN
    issue_type: IssueType = IssueType.PHASE
    parent_id: str | None = None
    owner: str = ""
    assignee: str = ""
    created_at: str = ""
    created_by: str = ""
    updated_at: str = ""
    closed_at: str | None = None
    close_reason: str | None = None
    description: str = ""
    notes: str = ""
    design: str = ""
    dependencies: list[Dependency] = field(default_factory=list)

    def validate(self) -> None:
        """Validate issue constraints.

        Raises ValueError if:
        - A phase issue has no parent_id
        """
        if self.issue_type == IssueType.PHASE and self.parent_id is None:
            raise ValueError("Phase issues must have a parent_id")
