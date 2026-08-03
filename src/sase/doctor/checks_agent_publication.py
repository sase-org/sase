"""Agent publication outbox checks for ``sase doctor``."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from sase.agents_sync.publication_outbox import (
    AGENT_PUBLICATION_OUTBOX_FILENAME,
    PUBLICATION_DROP_COMMAND,
    PUBLICATION_RETRY_COMMAND,
    AgentPublicationOutboxItem,
    configured_publication_max_attempts,
    publication_request_subject,
    snapshot_agent_publications_from_path,
)
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from pathlib import Path

    from sase.doctor.runner import DoctorContext

DEFAULT_PUBLICATION_STALLED_AGE_SECONDS = 24 * 60 * 60
_MAX_DETAIL_ROWS = 10
_REMEDIATION_COMMAND = PUBLICATION_RETRY_COMMAND
_RETIRED_REMEDIATION_COMMAND = PUBLICATION_DROP_COMMAND
_AXE_ENSURE_COMMAND = "sase axe ensure"
_AXE_STATUS_COMMAND = "sase axe status"
_AXE_CHOP_LIST_COMMAND = "sase axe chop list"
_PUBLICATIONS_LUMBERJACK = "publications"
_SIDECAR_PUBLICATION_CHOP = "sidecar_publication"


@dataclass(frozen=True, slots=True)
class _OutboxProblem:
    project_key: str
    project: str
    path: Path
    item: AgentPublicationOutboxItem
    reasons: tuple[str, ...]
    age_seconds: float | None
    command: str | None = None

    @property
    def retired(self) -> bool:
        return self.item.terminal

    @property
    def quarantined(self) -> bool:
        return self.item.quarantined and not self.item.terminal

    @property
    def stalled(self) -> bool:
        return (
            not self.retired
            and not self.quarantined
            and any(reason.startswith("stalled:") for reason in self.reasons)
        )

    @property
    def not_draining(self) -> bool:
        return (
            not self.retired
            and not self.quarantined
            and any(reason.startswith("not draining:") for reason in self.reasons)
        )

    @property
    def remediation_command(self) -> str:
        if self.command is not None:
            return self.command
        return _RETIRED_REMEDIATION_COMMAND if self.retired else _REMEDIATION_COMMAND

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
            "request_id": self.item.id,
            "kind": self.item.kind,
            "subject": publication_request_subject(self.item),
            "logical_key": self.item.logical_key,
            "global_agent": self.item.global_agent,
            "local_agent": self.item.local_agent,
            "primary_revision": self.item.primary_revision,
            "local_hood": self.item.local_hood,
            "bead_id": self.item.bead_id,
            "lineage_root": self.item.lineage_root,
            "plan_ref": self.item.plan_ref,
            "sidecar_kind": self.item.sidecar_kind,
            "attempts": self.item.attempts,
            "quarantined": self.item.quarantined,
            "retired": self.retired,
            "stalled": self.stalled,
            "not_draining": self.not_draining,
            "terminal_reason": self.item.terminal_reason,
            "last_error": self.item.last_error,
            "age_seconds": self.age_seconds,
            "reasons": self.reasons,
            "remediation_command": self.remediation_command,
        }


@dataclass(frozen=True, slots=True)
class _DrainIssue:
    reason: str
    remediation_command: str


class _OutboxProjectData(TypedDict):
    project_key: str
    project: str
    outbox_path: str
    request_count: int
    active_request_count: int
    quarantined_request_count: int
    retired_request_count: int
    stalled_request_count: int
    not_draining_request_count: int
    request_kind_counts: dict[str, int]
    active_kind_counts: dict[str, int]


def agent_publication_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default agent-publication check specs."""
    return (
        CheckSpec(
            id="state.agent_publication_outbox",
            group="state",
            title="Agent publication outbox",
            runner=lambda: _check_agent_publication_outbox(context),
        ),
    )


def _check_agent_publication_outbox(
    context: DoctorContext,
    *,
    now: float | None = None,
    stalled_attempts: int | None = None,
    stalled_age_seconds: float = DEFAULT_PUBLICATION_STALLED_AGE_SECONDS,
) -> DiagnosticCheck:
    projects_root = context.sase_home / "projects"
    checked_at = time.time() if now is None else now
    attempts_threshold = (
        configured_publication_max_attempts()
        if stalled_attempts is None
        else max(stalled_attempts, 1)
    )
    try:
        records = tuple(
            list_project_records(
                projects_root,
                "all",
                include_home=False,
                projects_only=True,
            )
        )
    except FileNotFoundError:
        return DiagnosticCheck(
            id="state.agent_publication_outbox",
            group="state",
            status="SKIP",
            title="Agent publication outbox",
            summary="SASE projects directory is not present",
            data={
                "projects_root": str(projects_root),
                "projects_root_exists": False,
            },
        )
    except Exception as exc:  # noqa: BLE001 - doctor reports lifecycle failures.
        error = f"{type(exc).__name__}: {exc}"
        return DiagnosticCheck(
            id="state.agent_publication_outbox",
            group="state",
            status="ERROR",
            title="Agent publication outbox",
            summary="project lifecycle records could not be loaded",
            details=(error,),
            next_steps=("Run `sase project list -s all -j`.",),
            data={
                "projects_root": str(projects_root),
                "projects_root_exists": projects_root.exists(),
                "error": error,
            },
        )

    if not records:
        return DiagnosticCheck(
            id="state.agent_publication_outbox",
            group="state",
            status="SKIP",
            title="Agent publication outbox",
            summary="no SASE projects are registered",
            data=_outbox_data(
                projects_root=projects_root,
                records=records,
                outboxes=(),
                problems=(),
                errors=(),
                stalled_attempts=attempts_threshold,
                stalled_age_seconds=stalled_age_seconds,
            ),
        )

    outboxes: list[_OutboxProjectData] = []
    problems: list[_OutboxProblem] = []
    errors: list[str] = []
    drain_issue: _DrainIssue | None = None
    drain_issue_checked = False
    for record in records:
        path = projects_root / record.project_name / AGENT_PUBLICATION_OUTBOX_FILENAME
        try:
            items = snapshot_agent_publications_from_path(path, record.project_name)
        except Exception as exc:  # noqa: BLE001 - one corrupt outbox is isolated.
            errors.append(
                f"{effective_project_name(record)}: could not read {path}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        if not drain_issue_checked and any(
            not item.quarantined and not item.terminal for item in items
        ):
            drain_issue = _publication_drain_issue()
            drain_issue_checked = True

        project_problems: list[_OutboxProblem] = []
        for item in items:
            problem = _problem_for_item(
                record,
                path,
                item,
                now=checked_at,
                stalled_attempts=attempts_threshold,
                stalled_age_seconds=stalled_age_seconds,
                drain_issue=(
                    drain_issue if not item.quarantined and not item.terminal else None
                ),
            )
            if problem is not None:
                project_problems.append(problem)
        project_problems_tuple = tuple(project_problems)
        outboxes.append(
            _outbox_project_data(record, path, items, project_problems_tuple)
        )
        problems.extend(project_problems_tuple)

    data = _outbox_data(
        projects_root=projects_root,
        records=records,
        outboxes=tuple(outboxes),
        problems=tuple(problems),
        errors=tuple(errors),
        stalled_attempts=attempts_threshold,
        stalled_age_seconds=stalled_age_seconds,
    )
    if errors:
        visible_errors = errors[:_MAX_DETAIL_ROWS]
        return DiagnosticCheck(
            id="state.agent_publication_outbox",
            group="state",
            status="ERROR",
            title="Agent publication outbox",
            summary=f"{len(errors)} publication outbox file(s) could not be read",
            details=tuple(visible_errors),
            next_steps=(
                "Inspect the listed agents-publication-outbox.json file(s) for malformed JSON or wrong project identity.",
            ),
            data={
                **data,
                "details_truncated": len(errors) > len(visible_errors),
            },
        )

    if problems:
        visible_problems = problems[:_MAX_DETAIL_ROWS]
        quarantined_count = sum(problem.quarantined for problem in problems)
        retired_count = sum(problem.retired for problem in problems)
        stalled_count = sum(problem.stalled for problem in problems)
        not_draining_count = sum(problem.not_draining for problem in problems)
        breakdown_parts = [
            f"{quarantined_count} quarantined",
            *((f"{retired_count} retired",) if retired_count else ()),
            *((f"{stalled_count} stalled",) if stalled_count else ()),
            *((f"{not_draining_count} not draining",) if not_draining_count else ()),
        ]
        breakdown = ", ".join(breakdown_parts)
        commands = tuple(
            dict.fromkeys(problem.remediation_command for problem in problems)
        )
        next_steps = tuple(
            _next_step_for_command(command) for command in sorted(commands)
        )
        return DiagnosticCheck(
            id="state.agent_publication_outbox",
            group="state",
            status="WARN",
            title="Agent publication outbox",
            summary=(
                f"{len(problems)} publication outbox request(s) need attention "
                f"({breakdown}); "
                f"run {' and '.join(f'`{command}`' for command in sorted(commands))}"
            ),
            details=tuple(problem.detail() for problem in visible_problems),
            next_steps=next_steps,
            data={
                **data,
                "details_truncated": len(problems) > len(visible_problems),
            },
        )

    total_requests = sum(int(row["request_count"]) for row in outboxes)
    return DiagnosticCheck(
        id="state.agent_publication_outbox",
        group="state",
        status="OK",
        title="Agent publication outbox",
        summary=(
            f"{total_requests} queued publication request(s); "
            "no quarantined or stalled requests"
        ),
        data=data,
    )


def _problem_for_item(
    record: ProjectRecordWire,
    path: Path,
    item: AgentPublicationOutboxItem,
    *,
    now: float,
    stalled_attempts: int,
    stalled_age_seconds: float,
    drain_issue: _DrainIssue | None,
) -> _OutboxProblem | None:
    age_seconds = _item_age_seconds(item, now=now)
    if item.terminal:
        return _OutboxProblem(
            record.project_name,
            effective_project_name(record),
            path,
            item,
            ("retired as unpublishable",),
            age_seconds,
        )
    if item.quarantined:
        return _OutboxProblem(
            record.project_name,
            effective_project_name(record),
            path,
            item,
            ("quarantined",),
            age_seconds,
        )

    reasons: list[str] = []
    command: str | None = None
    if drain_issue is not None:
        reasons.append(drain_issue.reason)
        command = drain_issue.remediation_command
    if item.attempts >= stalled_attempts:
        reasons.append(f"stalled: attempts >= {stalled_attempts}")
    if age_seconds is not None and age_seconds >= stalled_age_seconds:
        reasons.append(f"stalled: age >= {_format_duration(stalled_age_seconds)}")
    if not reasons:
        return None
    if command is None:
        command = _REMEDIATION_COMMAND
    return _OutboxProblem(
        record.project_name,
        effective_project_name(record),
        path,
        item,
        tuple(reasons),
        age_seconds,
        command,
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


def _outbox_project_data(
    record: ProjectRecordWire,
    path: Path,
    items: tuple[AgentPublicationOutboxItem, ...],
    problems: tuple[_OutboxProblem, ...],
) -> _OutboxProjectData:
    active_items = tuple(
        item for item in items if not item.quarantined and not item.terminal
    )
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
        "not_draining_request_count": sum(problem.not_draining for problem in problems),
        "request_kind_counts": _kind_counts(items),
        "active_kind_counts": _kind_counts(active_items),
    }


def _outbox_data(
    *,
    projects_root: Path,
    records: tuple[ProjectRecordWire, ...],
    outboxes: tuple[_OutboxProjectData, ...],
    problems: tuple[_OutboxProblem, ...],
    errors: tuple[str, ...],
    stalled_attempts: int,
    stalled_age_seconds: float,
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
        "not_draining_request_count": sum(problem.not_draining for problem in problems),
        "request_kind_counts": _sum_kind_counts(outboxes, "request_kind_counts"),
        "active_kind_counts": _sum_kind_counts(outboxes, "active_kind_counts"),
        "problems": tuple(problem.to_data() for problem in problems),
        "error_count": len(errors),
        "errors": errors,
        "thresholds": {
            "stalled_attempts": stalled_attempts,
            "stalled_age_seconds": stalled_age_seconds,
        },
        "remediation_command": _REMEDIATION_COMMAND,
        "retired_remediation_command": _RETIRED_REMEDIATION_COMMAND,
    }


def _publication_drain_issue() -> _DrainIssue | None:
    try:
        from sase.axe.status_collector import collect_axe_status_snapshot

        snapshot = collect_axe_status_snapshot()
    except Exception as exc:  # noqa: BLE001 - doctor should isolate AXE failures.
        return _DrainIssue(
            f"not draining: AXE status unavailable ({type(exc).__name__}: {exc})",
            _AXE_STATUS_COMMAND,
        )

    row = next(
        (
            item
            for item in snapshot.lumberjacks
            if getattr(item, "name", "") == _PUBLICATIONS_LUMBERJACK
        ),
        None,
    )
    if row is None or not bool(getattr(row, "configured", False)):
        return _DrainIssue(
            "not draining: publications lumberjack is not configured",
            _AXE_CHOP_LIST_COMMAND,
        )
    if _SIDECAR_PUBLICATION_CHOP not in tuple(getattr(row, "configured_chops", ())):
        return _DrainIssue(
            "not draining: publications lumberjack does not run sidecar_publication",
            _AXE_CHOP_LIST_COMMAND,
        )
    state = str(getattr(row, "state", "") or "not reporting")
    if state != "running":
        return _DrainIssue(
            f"not draining: publications lumberjack is {state}",
            _AXE_ENSURE_COMMAND,
        )
    return None


def _next_step_for_command(command: str) -> str:
    if command == _REMEDIATION_COMMAND:
        return (
            f"Run `{_REMEDIATION_COMMAND}` to release quarantined requests and retry "
            "publication."
        )
    if command == _RETIRED_REMEDIATION_COMMAND:
        return (
            f"Run `{_RETIRED_REMEDIATION_COMMAND}` to drop retired requests that can "
            "never be published."
        )
    if command == _AXE_ENSURE_COMMAND:
        return (
            f"Run `{_AXE_ENSURE_COMMAND}` to start or heal the publications lumberjack."
        )
    if command == _AXE_CHOP_LIST_COMMAND:
        return (
            f"Run `{_AXE_CHOP_LIST_COMMAND}` and confirm the publications lumberjack "
            "includes sidecar_publication."
        )
    return f"Run `{command}`."


def _kind_counts(items: tuple[AgentPublicationOutboxItem, ...]) -> dict[str, int]:
    return dict(sorted(Counter(item.kind for item in items).items()))


def _sum_kind_counts(
    outboxes: tuple[_OutboxProjectData, ...],
    field: Literal["request_kind_counts", "active_kind_counts"],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in outboxes:
        counts.update(row[field])
    return dict(sorted(counts.items()))


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


__all__ = ["agent_publication_check_specs"]
