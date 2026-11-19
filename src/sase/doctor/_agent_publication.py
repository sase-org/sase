"""Shared types and helpers for agent-publication doctor checks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from sase.agents_sync.prompt_archive.terminal import (
    is_terminal_prompt_archive_reason,
    terminal_obligations_path,
)
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
    def parked(self) -> bool:
        return self.item.parked_reason is not None

    @property
    def stalled(self) -> bool:
        return not self.retired and not self.quarantined and not self.parked

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
            "parked": self.parked,
            "parked_reason": self.item.parked_reason,
            "parked_since": self.item.parked_since,
            "parked_checked_at": self.item.parked_checked_at,
            "parked_rules_version": self.item.parked_rules_version,
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


def is_settled_terminal(item: AgentPublicationOutboxItem) -> bool:
    """Return whether *item* is an audited terminal prompt archive.

    Rows retired as ``prompt_archive_unrecoverable`` are settled: they are
    counted and point at the terminal-obligations audit record, but they are
    never doctor issues.
    """

    return bool(
        item.terminal and is_terminal_prompt_archive_reason(item.terminal_reason)
    )


@dataclass(frozen=True, slots=True)
class SettledTerminal:
    project_key: str
    project: str
    path: Path
    item: AgentPublicationOutboxItem

    def detail(self) -> str:
        reason = self.item.terminal_reason or "unrecoverable prompt archive"
        return (
            f"{self.project}: {publication_request_subject(self.item)} settled "
            f"as {reason}; audited in {terminal_obligations_path().name}"
        )

    def to_data(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project": self.project,
            "outbox_path": str(self.path),
            "global_agent": self.item.global_agent,
            "local_agent": self.item.local_agent,
            "primary_revision": self.item.primary_revision,
            "local_hood": self.item.local_hood,
            "attempts": self.item.attempts,
            "terminal_reason": self.item.terminal_reason,
            "audit_path": str(terminal_obligations_path()),
        }


@dataclass(frozen=True, slots=True)
class OutboxGroup:
    """One doctor issue: every open row for one (project, signature) cause."""

    project_key: str
    project: str
    signature: str
    problems: tuple[OutboxProblem, ...]

    @property
    def count(self) -> int:
        return len(self.problems)

    @property
    def total_attempts(self) -> int:
        return sum(problem.item.attempts for problem in self.problems)

    @property
    def first_time(self) -> float | None:
        stamps = [
            problem.item.created_at or problem.item.updated_at
            for problem in self.problems
        ]
        stamps = [stamp for stamp in stamps if stamp > 0]
        return min(stamps) if stamps else None

    @property
    def last_time(self) -> float | None:
        stamps = [problem.item.updated_at for problem in self.problems]
        stamps = [stamp for stamp in stamps if stamp > 0]
        return max(stamps) if stamps else None

    @property
    def kinds(self) -> tuple[str, ...]:
        kinds: list[str] = []
        for problem in self.problems:
            for kind in (
                ("retired" if problem.retired else None),
                ("quarantined" if problem.quarantined else None),
                ("parked" if problem.parked else None),
                ("stalled" if problem.stalled else None),
            ):
                if kind is not None and kind not in kinds:
                    kinds.append(kind)
        return tuple(kinds)

    @property
    def remediation_command(self) -> str:
        if any(problem.retired for problem in self.problems):
            return RETIRED_REMEDIATION_COMMAND
        return REMEDIATION_COMMAND

    def detail(self) -> str:
        first = (
            _format_duration(self.last_time - self.first_time)
            if self.first_time is not None and self.last_time is not None
            else "unknown"
        )
        return (
            f"{self.project}: {self.count} request(s) "
            f"({', '.join(self.kinds) or 'attention'}) "
            f"under signature {self.signature[:16]}…, "
            f"{self.total_attempts} attempt(s) over {first}"
        )

    def to_data(self, standing: dict[str, Any] | None = None) -> dict[str, object]:
        data: dict[str, object] = {
            "project_key": self.project_key,
            "project": self.project,
            "signature": self.signature,
            "request_count": self.count,
            "total_attempts": self.total_attempts,
            "first_time": self.first_time,
            "last_time": self.last_time,
            "kinds": list(self.kinds),
            "remediation_command": self.remediation_command,
            "problems": tuple(problem.to_data() for problem in self.problems),
        }
        if standing is not None:
            data["standing"] = standing
        return data


def _outbox_signature_for(item: AgentPublicationOutboxItem) -> str:
    """Return the stable grouping signature for one outbox row.

    The error-groups normalizer masks volatile tokens so one cause keeps one
    signature across ticks. Classifier trouble fails open to the failure
    class, which still groups deterministically.
    """

    text = item.last_error or publication_request_subject(item)
    try:
        from sase.core.axe_error_facade import normalize_error_signature

        signature = normalize_error_signature(text)
    except Exception:  # noqa: BLE001 - doctor fails open to a coarse signature.
        signature = ""
    if signature:
        return signature
    return f"unclassified:{classify_publication_error(item.last_error)}"


def group_outbox_problems(
    problems: tuple[OutboxProblem, ...] | list[OutboxProblem],
) -> tuple[OutboxGroup, ...]:
    """Fold open problems into one group per (project, signature) cause.

    Groups keep first-seen order so unchanged state renders the same issue
    list on every tick.
    """

    groups: dict[tuple[str, str], list[OutboxProblem]] = {}
    for problem in problems:
        key = (problem.project_key, _outbox_signature_for(problem.item))
        groups.setdefault(key, []).append(problem)
    return tuple(
        OutboxGroup(
            project_key=key[0],
            project=members[0].project,
            signature=key[1],
            problems=tuple(members),
        )
        for key, members in groups.items()
    )


class OutboxProjectData(TypedDict):
    project_key: str
    project: str
    outbox_path: str
    request_count: int
    active_request_count: int
    quarantined_request_count: int
    retired_request_count: int
    stalled_request_count: int
    parked_request_count: int


def _parked_age_seconds(
    item: AgentPublicationOutboxItem,
    *,
    now: float,
) -> float | None:
    base = item.parked_since
    if base is None:
        base = item.parked_checked_at
    if base is None:
        return _item_age_seconds(item, now=now)
    if base <= 0:
        return None
    return max(now - base, 0.0)


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
    if is_settled_terminal(item):
        return None
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
    if item.parked_reason is not None:
        parked_age = _parked_age_seconds(item, now=now)
        return OutboxProblem(
            record.project_name,
            effective_project_name(record),
            path,
            item,
            (f"parked: {item.parked_reason}",),
            parked_age if parked_age is not None else age_seconds,
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
        "parked_request_count": sum(problem.parked for problem in problems),
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
    settled: tuple[SettledTerminal, ...] = (),
    groups: tuple[OutboxGroup, ...] = (),
    standing_alerts: tuple[dict[str, Any], ...] = (),
    standing_by_group: dict[tuple[str, str], dict[str, Any]] | None = None,
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
        "parked_request_count": sum(problem.parked for problem in problems),
        "problems": tuple(problem.to_data() for problem in problems),
        "settled_request_count": len(settled),
        "settled": tuple(entry.to_data() for entry in settled),
        "settled_audit_path": str(terminal_obligations_path()),
        "groups": tuple(
            group.to_data(
                (standing_by_group or {}).get((group.project_key, group.signature))
            )
            for group in groups
        ),
        "standing_alert_count": len(standing_alerts),
        "standing_alerts": standing_alerts,
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
