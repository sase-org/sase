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


class BeadTier(Enum):
    PLAN = "plan"
    EPIC = "epic"
    LEGEND = "legend"


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
    tier: BeadTier | None = None
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
    is_ready_to_work: bool = False
    epic_count: int | None = None
    changespec_name: str = ""
    changespec_bug_id: str = ""
    dependencies: list[Dependency] = field(default_factory=list)

    def validate(self) -> None:
        """Validate issue constraints.

        Raises ValueError if:
        - A phase issue has no parent_id
        - A phase issue has is_ready_to_work=True (only plans carry the flag)
        """
        if self.issue_type == IssueType.PHASE and self.parent_id is None:
            raise ValueError("Phase issues must have a parent_id")
        if self.issue_type == IssueType.PHASE and self.tier is not None:
            raise ValueError("Phase issues cannot carry plan tier metadata")
        if self.issue_type == IssueType.PHASE and self.is_ready_to_work:
            raise ValueError("Only plan issues can be marked is_ready_to_work")
        if self.issue_type != IssueType.PLAN and self.epic_count is not None:
            raise ValueError("Only plan issues can carry epic_count")
        if self.epic_count is not None:
            if self.tier != BeadTier.LEGEND:
                raise ValueError("Only legend plan beads can carry epic_count")
            if self.epic_count <= 0:
                raise ValueError("epic_count must be a positive integer")
        if self.issue_type == IssueType.PHASE and (
            self.changespec_name or self.changespec_bug_id
        ):
            raise ValueError("Phase issues cannot carry ChangeSpec metadata")
        if self.changespec_bug_id and not self.changespec_name:
            raise ValueError("changespec_bug_id requires changespec_name")
