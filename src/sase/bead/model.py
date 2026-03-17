"""Issue and dependency data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class IssueType(Enum):
    EPIC = "epic"
    CHILD = "child"


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
    issue_type: IssueType = IssueType.CHILD
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
        - A child issue has no parent_id
        - An epic issue has a parent_id
        """
        if self.issue_type == IssueType.CHILD and self.parent_id is None:
            raise ValueError("Child issues must have a parent_id")
        if self.issue_type == IssueType.EPIC and self.parent_id is not None:
            raise ValueError("Epic issues must not have a parent_id")
