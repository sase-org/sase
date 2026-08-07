"""Issue and dependency data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Status(Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    READY = "ready"
    SNOOZED = "snoozed"
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


class ReopenCause(Enum):
    """Why an archived close was undone.

    One variant per reducer branch in sase-core that reopens a bead.
    """

    PLUS_ONE = "plus_one"
    OPEN = "open"
    UPDATE = "update"
    EPIC_PRECLAIM = "epic_preclaim"


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


@dataclass(frozen=True)
class CloseRecord:
    """One close episode that has since been undone.

    The flat ``closed_at`` / ``close_reason`` / ``resolution`` fields on
    :class:`Issue` always describe the *current* close; a close record is
    strictly the past. Every record carries a ``reopened_at``, because a
    record only comes into existence once the close is undone.
    """

    closed_at: str
    reopened_at: str
    reopened_via: ReopenCause
    close_reason: str | None = None
    resolution: Resolution | None = None
    reopened_by: str | None = None

    def validate(self) -> None:
        if not self.closed_at.strip():
            raise ValueError("close history closed_at cannot be empty or blank")
        if not self.reopened_at.strip():
            raise ValueError("close history reopened_at cannot be empty or blank")
        if self.reopened_by is not None and not self.reopened_by.strip():
            raise ValueError("close history reopened_by cannot be empty or blank")


@dataclass(frozen=True)
class SnoozeRecord:
    """The wake conditions a snoozed task bead is waiting on.

    Mirrors ``BeadSnoozeWire`` in sase-core. The record exists exactly while
    the status is ``snoozed`` and is cleared on wake, so no flat field can
    drift out of sync with the status.
    """

    until: str
    snoozed_at: str
    snoozed_by: str
    plus_one_target: int | None = None
    plus_one_baseline: int | None = None
    reason: str = ""

    @property
    def plus_ones_remaining(self) -> int | None:
        """Return how many more +1s would wake this bead, if any target."""
        if self.plus_one_target is None:
            return None
        return max(0, self.plus_one_target - (self.plus_one_baseline or 0))

    def validate(self) -> None:
        if not self.snoozed_at.strip():
            raise ValueError("bead snooze snoozed_at cannot be empty or blank")
        if not self.snoozed_by.strip():
            raise ValueError("bead snooze snoozed_by cannot be empty or blank")
        _parse_snooze_timestamp(self.until, "until")
        if self.plus_one_target is not None:
            baseline = self.plus_one_baseline or 0
            if self.plus_one_target <= baseline:
                raise ValueError(
                    "bead snooze plus_one_target must exceed plus_one_baseline: "
                    f"{self.plus_one_target} <= {baseline}"
                )


def _parse_snooze_timestamp(value: str, field_name: str) -> datetime:
    """Parse one snooze timestamp, requiring an explicit UTC offset.

    A snooze is compared against wall-clock time on several surfaces, so an
    offset-less timestamp is rejected rather than silently meaning different
    instants to different readers. This mirrors ``parse_snooze_timestamp`` in
    sase-core, which accepts RFC-3339 with an offset and nothing else.
    """
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"bead snooze {field_name} must be an RFC-3339 timestamp with an "
            f"offset: {value!r} ({exc})"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(
            f"bead snooze {field_name} must be an RFC-3339 timestamp with an "
            f"offset: {value!r} (missing UTC offset)"
        )
    return parsed


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
    close_history: list[CloseRecord] = field(default_factory=list)
    snooze: SnoozeRecord | None = None
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
        - A non-task issue has ready or snoozed status
        - Snooze metadata and snoozed status disagree
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
        # close_history is deliberately unrestricted by issue type: plans and
        # phases are reopened by ``sase bead open`` and by epic work preclaims.
        for record in self.close_history:
            record.validate()
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
        if self.status == Status.SNOOZED and self.issue_type != IssueType.TASK:
            raise ValueError("Only task issues can have snoozed status")
        if self.status == Status.SNOOZED and self.snooze is None:
            raise ValueError("snoozed issues must carry snooze metadata")
        if self.status != Status.SNOOZED and self.snooze is not None:
            raise ValueError("Only snoozed issues can carry snooze metadata")
        if self.snooze is not None:
            self.snooze.validate()
        if self.changespec_bug_id and not self.changespec_name:
            raise ValueError("changespec_bug_id requires changespec_name")
        if self.status != Status.CLOSED and self.resolution is not None:
            raise ValueError("Only closed issues can carry resolution metadata")


@dataclass
class BeadSearchMatch:
    issue: Issue
    matched_fields: list[str]
