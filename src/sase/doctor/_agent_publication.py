"""Shared types and helpers for agent-publication doctor checks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from sase.agents_sync.publication_outbox import (
    PUBLICATION_DROP_COMMAND,
    PUBLICATION_RETRY_COMMAND,
    AgentPublicationOutboxItem,
    publication_request_subject,
)
from sase.agents_sync.publication_outbox_diagnostics import (
    classify_publication_error,
)
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)

REMEDIATION_COMMAND = PUBLICATION_RETRY_COMMAND
RETIRED_REMEDIATION_COMMAND = PUBLICATION_DROP_COMMAND


@dataclass(frozen=True, slots=True)
class OutboxProblem:
    project_key: str
    project: str
    path: Path
    item: AgentPublicationOutboxItem
    reasons: tuple[str, ...]
    age_seconds: float | None

    @property
    def retired(self) -> bool:
        return self.item.terminal

    @property
    def quarantined(self) -> bool:
        return self.item.quarantined and not self.item.terminal

    @property
    def stalled(self) -> bool:
        return not self.retired and not self.quarantined

    @property
    def remediation_command(self) -> str:
        return RETIRED_REMEDIATION_COMMAND if self.retired else REMEDIATION_COMMAND

    def detail(self) -> str:
        reason = ", ".join(self.reasons)
        age = (
            f", age {_format_duration(self.age_seconds)}"
            if self.age_seconds is not None
            else ""
        )
        error = f", last error: {self.item.last_error}" if self.item.last_error else ""
        return (
            f"{self.project}: {publication_request_subject(self.item)} "
            f"{reason} after "
            f"{self.item.attempts} attempt(s){age}{error}"
        )

    def to_data(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project": self.project,
            "outbox_path": str(self.path),
            "global_agent": self.item.global_agent,
            "local_agent": self.item.local_agent,
            "primary_revision": self.item.primary_revision,
            "requested_revision": self.item.original_revision,
            "local_hood": self.item.local_hood,
            "attempts": self.item.attempts,
            "quarantined": self.item.quarantined,
            "retired": self.retired,
            "terminal_reason": self.item.terminal_reason,
            "last_error": self.item.last_error,
            "age_seconds": self.age_seconds,
            "reasons": self.reasons,
            "remediation_command": self.remediation_command,
        }


@dataclass(frozen=True, slots=True)
class OwnerManifestProblem:
    project_key: str
    project: str
    path: Path
    error: str
    remediation_command: str = REMEDIATION_COMMAND

    def detail(self) -> str:
        return (
            f"{self.project}: local owner manifest {self.path} does not decode: "
            f"{self.error}"
        )

    def to_data(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project": self.project,
            "manifest_path": str(self.path),
            "error": self.error,
            "remediation_command": self.remediation_command,
        }


class OutboxProjectData(TypedDict):
    project_key: str
    project: str
    outbox_path: str
    request_count: int
    active_request_count: int
    quarantined_request_count: int
    retired_request_count: int
    stalled_request_count: int


def problem_for_item(
    record: ProjectRecordWire,
    path: Path,
    item: AgentPublicationOutboxItem,
    *,
    now: float,
    stalled_attempts: int,
    stalled_age_seconds: float,
) -> OutboxProblem | None:
    age_seconds = _item_age_seconds(item, now=now)
    if item.terminal:
        return OutboxProblem(
            record.project_name,
            effective_project_name(record),
            path,
            item,
            ("retired as unpublishable",),
            age_seconds,
        )
    if item.quarantined:
        return OutboxProblem(
            record.project_name,
            effective_project_name(record),
            path,
            item,
            ("quarantined",),
            age_seconds,
        )

    reasons: list[str] = []
    if item.attempts >= stalled_attempts:
        reasons.append(f"stalled: attempts >= {stalled_attempts}")
    if age_seconds is not None and age_seconds >= stalled_age_seconds:
        reasons.append(f"stalled: age >= {_format_duration(stalled_age_seconds)}")
    if not reasons:
        return None
    return OutboxProblem(
        record.project_name,
        effective_project_name(record),
        path,
        item,
        tuple(reasons),
        age_seconds,
    )


def _item_age_seconds(
    item: AgentPublicationOutboxItem,
    *,
    now: float,
) -> float | None:
    timestamp = item.created_at or item.updated_at
    if timestamp <= 0:
        return None
    return max(now - timestamp, 0.0)


def outbox_project_data(
    record: ProjectRecordWire,
    path: Path,
    items: tuple[AgentPublicationOutboxItem, ...],
    problems: tuple[OutboxProblem, ...],
) -> OutboxProjectData:
    return {
        "project_key": record.project_name,
        "project": effective_project_name(record),
        "outbox_path": str(path),
        "request_count": len(items),
        "active_request_count": sum(
            not item.quarantined and not item.terminal for item in items
        ),
        "quarantined_request_count": sum(
            item.quarantined and not item.terminal for item in items
        ),
        "retired_request_count": sum(item.terminal for item in items),
        "stalled_request_count": sum(problem.stalled for problem in problems),
    }


def outbox_data(
    *,
    projects_root: Path,
    records: tuple[ProjectRecordWire, ...],
    outboxes: tuple[OutboxProjectData, ...],
    problems: tuple[OutboxProblem, ...],
    errors: tuple[str, ...],
    migration_notices: tuple[str, ...],
    owner_manifest_problems: tuple[OwnerManifestProblem, ...],
    owner_manifest_errors: tuple[str, ...],
    stalled_attempts: int,
    stalled_age_seconds: float,
    last_error_histogram: dict[str, int] | None = None,
    oldest_active_age_seconds: float | None = None,
    sidecar_states: tuple[dict[str, Any], ...] = (),
    stale_requested_revision_count: int = 0,
    stale_requested_revisions: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "projects_root": str(projects_root),
        "projects_root_exists": projects_root.exists(),
        "project_count": len(records),
        "outboxes": outboxes,
        "request_count": sum(int(row["request_count"]) for row in outboxes),
        "active_request_count": sum(
            int(row["active_request_count"]) for row in outboxes
        ),
        "quarantined_request_count": sum(problem.quarantined for problem in problems),
        "retired_request_count": sum(problem.retired for problem in problems),
        "stalled_request_count": sum(problem.stalled for problem in problems),
        "problems": tuple(problem.to_data() for problem in problems),
        "error_count": len(errors),
        "errors": errors,
        "migration_notice_count": len(migration_notices),
        "migration_notices": migration_notices,
        "last_error_histogram": dict(last_error_histogram or {}),
        "oldest_active_age_seconds": oldest_active_age_seconds,
        "sidecar_states": sidecar_states,
        "owner_manifest_problem_count": len(owner_manifest_problems),
        "owner_manifest_problems": tuple(
            problem.to_data() for problem in owner_manifest_problems
        ),
        "owner_manifest_error_count": len(owner_manifest_errors),
        "owner_manifest_errors": owner_manifest_errors,
        "stale_requested_revision_count": stale_requested_revision_count,
        "stale_requested_revisions": list(stale_requested_revisions),
        "thresholds": {
            "stalled_attempts": stalled_attempts,
            "stalled_age_seconds": stalled_age_seconds,
        },
        "remediation_command": REMEDIATION_COMMAND,
        "retired_remediation_command": RETIRED_REMEDIATION_COMMAND,
    }


def last_error_histogram(
    items: list[AgentPublicationOutboxItem] | tuple[AgentPublicationOutboxItem, ...],
) -> dict[str, int]:
    """Count last-error classes over items that record an error."""

    return dict(
        Counter(
            classify_publication_error(item.last_error)
            for item in items
            if item.last_error
        )
    )


def oldest_active_age_seconds(
    items: list[AgentPublicationOutboxItem] | tuple[AgentPublicationOutboxItem, ...],
    *,
    now: float,
) -> float | None:
    """Return the greatest age of any non-terminal request, if any exists."""

    ages = [
        age
        for item in items
        if not item.terminal
        for age in (_item_age_seconds(item, now=now),)
        if age is not None
    ]
    return max(ages) if ages else None


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    total = max(int(seconds), 0)
    days, remainder = divmod(total, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"
