"""Issue and dependency data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class IssueType(Enum):
    PLAN = "plan"
    PHASE = "phase"
    TASK = "task"


class BeadTier(Enum):
    PLAN = "plan"
    EPIC = "epic"


class Resolution(Enum):
    DONE = "done"
    CANCELED = "canceled"
    SUPERSEDED = "superseded"


class PhaseSize(Enum):
    XSMALL = "xsmall"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    XLARGE = "xlarge"


@dataclass
class Dependency:
    issue_id: str
    depends_on_id: str
    created_at: str
    created_by: str = ""


@dataclass(frozen=True)
class TaskPlusOneEvidence:
    timestamp: str
    reporter: str
    note: str
    refs: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.timestamp.strip():
            raise ValueError("task +1 evidence timestamp cannot be empty or blank")
        if not self.reporter.strip():
            raise ValueError("task +1 reporter cannot be empty or blank")
        if not self.note.strip():
            raise ValueError("task +1 note cannot be empty or blank")
        from sase.artifact_ref_lists import normalize_artifact_ref_list

        if normalize_artifact_ref_list(self.refs) != self.refs:
            raise ValueError(
                "task +1 evidence refs must be normalized and deduplicated"
            )


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
    resolution: Resolution | None = None
    description: str = ""
    notes: str = ""
    design: str = ""
    refs: list[str] = field(default_factory=list)
    plus_one_evidence: list[TaskPlusOneEvidence] = field(default_factory=list)
    model: str = ""
    size: PhaseSize | None = None
    is_ready_to_work: bool = False
    changespec_name: str = ""
    changespec_bug_id: str = ""
    dependencies: list[Dependency] = field(default_factory=list)

    @property
    def plus_one_count(self) -> int:
        return len(self.plus_one_evidence)

    def validate(self) -> None:
        """Validate issue constraints.

        Raises ValueError if:
        - A phase issue has no parent_id
        - A task issue has a parent_id
        - A non-plan issue carries plan-only metadata
        - A plan issue carries phase/task size metadata
        - A non-task issue has ready status
        """
        if self.issue_type == IssueType.PHASE and self.parent_id is None:
            raise ValueError("Phase issues must have a parent_id")
        if self.issue_type == IssueType.PHASE and self.tier is not None:
            raise ValueError("Phase issues cannot carry plan tier metadata")
        if self.issue_type == IssueType.TASK and self.parent_id is not None:
            raise ValueError("Task issues cannot have a parent_id")
        if self.issue_type == IssueType.TASK and self.tier is not None:
            raise ValueError("Task issues cannot carry plan tier metadata")
        if self.issue_type != IssueType.TASK and self.plus_one_evidence:
            raise ValueError("Only task issues can carry +1 evidence")
        reporters: set[str] = set()
        for evidence in self.plus_one_evidence:
            evidence.validate()
            if evidence.reporter in reporters:
                raise ValueError(f"duplicate task +1 reporter: {evidence.reporter}")
            reporters.add(evidence.reporter)
        if self.issue_type != IssueType.PLAN and self.is_ready_to_work:
            raise ValueError("Only plan issues can be marked is_ready_to_work")
        if self.issue_type == IssueType.PLAN and self.size is not None:
            raise ValueError("Only phase and task issues can carry size metadata")
        if self.issue_type != IssueType.PLAN and (
            self.changespec_name or self.changespec_bug_id
        ):
            raise ValueError("Only plan issues can carry ChangeSpec metadata")
        if self.status == Status.READY and self.issue_type != IssueType.TASK:
            raise ValueError("Only task issues can have ready status")
        if self.changespec_bug_id and not self.changespec_name:
            raise ValueError("changespec_bug_id requires changespec_name")
        if self.status != Status.CLOSED and self.resolution is not None:
            raise ValueError("Only closed issues can carry resolution metadata")


@dataclass
class BeadSearchMatch:
    issue: Issue
    matched_fields: list[str]
