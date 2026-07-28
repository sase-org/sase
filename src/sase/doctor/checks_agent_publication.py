"""Agent publication outbox checks for ``sase doctor``."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, Any, TypedDict

from sase.agents_sync.publication_outbox import (
    AGENT_PUBLICATION_OUTBOX_FILENAME,
    AgentPublicationOutboxItem,
    configured_publication_max_attempts,
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
_REMEDIATION_COMMAND = "sase agent sync --retry-quarantined"


@dataclass(frozen=True, slots=True)
class _OutboxProblem:
    project_key: str
    project: str
    path: Path
    item: AgentPublicationOutboxItem
    reasons: tuple[str, ...]
    age_seconds: float | None

    @property
    def quarantined(self) -> bool:
        return self.item.quarantined

    def detail(self) -> str:
        reason = ", ".join(self.reasons)
        age = (
            f", age {_format_duration(self.age_seconds)}"
            if self.age_seconds is not None
            else ""
        )
        error = f", last error: {self.item.last_error}" if self.item.last_error else ""
        return (
            f"{self.project}: {self.item.global_agent}@"
            f"{self.item.primary_revision[:12]} {reason} after "
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
            "local_hood": self.item.local_hood,
            "attempts": self.item.attempts,
            "quarantined": self.item.quarantined,
            "last_error": self.item.last_error,
            "age_seconds": self.age_seconds,
            "reasons": self.reasons,
        }


class _OutboxProjectData(TypedDict):
    project_key: str
    project: str
    outbox_path: str
    request_count: int
    active_request_count: int
    quarantined_request_count: int
    stalled_request_count: int


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

        project_problems: list[_OutboxProblem] = []
        for item in items:
            problem = _problem_for_item(
                record,
                path,
                item,
                now=checked_at,
                stalled_attempts=attempts_threshold,
                stalled_age_seconds=stalled_age_seconds,
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
        stalled_count = len(problems) - quarantined_count
        return DiagnosticCheck(
            id="state.agent_publication_outbox",
            group="state",
            status="WARN",
            title="Agent publication outbox",
            summary=(
                f"{len(problems)} publication outbox request(s) need attention "
                f"({quarantined_count} quarantined, {stalled_count} stalled); "
                f"run `{_REMEDIATION_COMMAND}`"
            ),
            details=tuple(problem.detail() for problem in visible_problems),
            next_steps=(
                f"Run `{_REMEDIATION_COMMAND}` to release quarantined requests and retry publication.",
            ),
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
) -> _OutboxProblem | None:
    age_seconds = _item_age_seconds(item, now=now)
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
    if item.attempts >= stalled_attempts:
        reasons.append(f"stalled: attempts >= {stalled_attempts}")
    if age_seconds is not None and age_seconds >= stalled_age_seconds:
        reasons.append(f"stalled: age >= {_format_duration(stalled_age_seconds)}")
    if not reasons:
        return None
    return _OutboxProblem(
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


def _outbox_project_data(
    record: ProjectRecordWire,
    path: Path,
    items: tuple[AgentPublicationOutboxItem, ...],
    problems: tuple[_OutboxProblem, ...],
) -> _OutboxProjectData:
    quarantined_count = sum(item.quarantined for item in items)
    return {
        "project_key": record.project_name,
        "project": effective_project_name(record),
        "outbox_path": str(path),
        "request_count": len(items),
        "active_request_count": sum(not item.quarantined for item in items),
        "quarantined_request_count": quarantined_count,
        "stalled_request_count": sum(not problem.quarantined for problem in problems),
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
        "stalled_request_count": sum(not problem.quarantined for problem in problems),
        "problems": tuple(problem.to_data() for problem in problems),
        "error_count": len(errors),
        "errors": errors,
        "thresholds": {
            "stalled_attempts": stalled_attempts,
            "stalled_age_seconds": stalled_age_seconds,
        },
        "remediation_command": _REMEDIATION_COMMAND,
    }


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
