"""Agent publication outbox checks for ``sase doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, TypedDict

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.targets import resolve_sync_targets
from sase.agents_sync.publication_outbox import (
    AGENT_PUBLICATION_OUTBOX_FILENAME,
    PUBLICATION_DROP_COMMAND,
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    PUBLICATION_RETRY_COMMAND,
    AgentPublicationOutboxItem,
    configured_publication_max_attempts,
    publication_request_subject,
    snapshot_publication_document_from_path,
)
from sase.agents_sync.v2_io import owner_manifest_path, read_owner_manifest
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.config import require_agent_owner_identity
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
    is_disabled_project_lifecycle_state,
)
from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

DEFAULT_PUBLICATION_STALLED_AGE_SECONDS = 24 * 60 * 60
_MAX_DETAIL_ROWS = 10
_REMEDIATION_COMMAND = PUBLICATION_RETRY_COMMAND
_RETIRED_REMEDIATION_COMMAND = PUBLICATION_DROP_COMMAND
_MIGRATION_NEXT_STEP = (
    f"Obsolete publication requests were dropped while reading the outbox; run "
    f"`{PUBLICATION_RETRY_COMMAND}` to rewrite it at schema "
    f"{PUBLICATION_OUTBOX_SCHEMA_VERSION} and clear this notice."
)


@dataclass(frozen=True, slots=True)
class _OutboxProblem:
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
            "global_agent": self.item.global_agent,
            "local_agent": self.item.local_agent,
            "primary_revision": self.item.primary_revision,
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
class _OwnerManifestProblem:
    project_key: str
    project: str
    path: Path
    error: str
    remediation_command: str = _REMEDIATION_COMMAND

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


class _OutboxProjectData(TypedDict):
    project_key: str
    project: str
    outbox_path: str
    request_count: int
    active_request_count: int
    quarantined_request_count: int
    retired_request_count: int
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
                migration_notices=(),
                owner_manifest_problems=(),
                owner_manifest_errors=(),
                stalled_attempts=attempts_threshold,
                stalled_age_seconds=stalled_age_seconds,
            ),
        )

    outboxes: list[_OutboxProjectData] = []
    problems: list[_OutboxProblem] = []
    errors: list[str] = []
    migration_notices: list[str] = []
    owner_manifest_problems, owner_manifest_errors = _owner_manifest_problems(
        context,
        records,
    )
    for record in records:
        path = projects_root / record.project_name / AGENT_PUBLICATION_OUTBOX_FILENAME
        try:
            document = snapshot_publication_document_from_path(
                path,
                record.project_name,
            )
        except Exception as exc:  # noqa: BLE001 - one corrupt outbox is isolated.
            errors.append(
                f"{effective_project_name(record)}: could not read {path}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        items = document.items
        migration_notices.extend(
            f"{effective_project_name(record)}: {notice}" for notice in document.notices
        )

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
        migration_notices=tuple(migration_notices),
        owner_manifest_problems=owner_manifest_problems,
        owner_manifest_errors=owner_manifest_errors,
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

    if problems or owner_manifest_problems or migration_notices:
        visible_problems = problems[:_MAX_DETAIL_ROWS]
        remaining_detail_rows = _MAX_DETAIL_ROWS - len(visible_problems)
        visible_manifest_problems = owner_manifest_problems[:remaining_detail_rows]
        remaining_detail_rows -= len(visible_manifest_problems)
        visible_notices = tuple(migration_notices[:remaining_detail_rows])
        quarantined_count = sum(problem.quarantined for problem in problems)
        retired_count = sum(problem.retired for problem in problems)
        stalled_count = sum(problem.stalled for problem in problems)
        breakdown_parts = [
            *((f"{quarantined_count} quarantined",) if quarantined_count else ()),
            *((f"{retired_count} retired",) if retired_count else ()),
            *((f"{stalled_count} stalled",) if stalled_count else ()),
            *(
                (f"{len(owner_manifest_problems)} unreadable owner manifest",)
                if owner_manifest_problems
                else ()
            ),
            *(
                (f"{len(migration_notices)} obsolete request kind(s) dropped",)
                if migration_notices
                else ()
            ),
        ]
        breakdown = ", ".join(breakdown_parts) or "needs attention"
        commands = tuple(
            dict.fromkeys(
                (
                    *(problem.remediation_command for problem in problems),
                    *(
                        problem.remediation_command
                        for problem in owner_manifest_problems
                    ),
                )
            )
        )
        next_steps = (
            *(_next_step_for_command(command) for command in sorted(commands)),
            *((_MIGRATION_NEXT_STEP,) if migration_notices else ()),
        )
        attention_count = (
            len(problems) + len(owner_manifest_problems) + len(migration_notices)
        )
        remediation = (
            "; run " + " and ".join(f"`{command}`" for command in sorted(commands))
            if commands
            else ""
        )
        return DiagnosticCheck(
            id="state.agent_publication_outbox",
            group="state",
            status="WARN",
            title="Agent publication outbox",
            summary=(
                f"{attention_count} agent publication issue(s) need attention "
                f"({breakdown}){remediation}"
            ),
            details=(
                *(problem.detail() for problem in visible_problems),
                *(problem.detail() for problem in visible_manifest_problems),
                *visible_notices,
            ),
            next_steps=next_steps,
            data={
                **data,
                "details_truncated": (
                    len(problems) > len(visible_problems)
                    or len(owner_manifest_problems) > len(visible_manifest_problems)
                    or len(migration_notices) > len(visible_notices)
                ),
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


def _outbox_data(
    *,
    projects_root: Path,
    records: tuple[ProjectRecordWire, ...],
    outboxes: tuple[_OutboxProjectData, ...],
    problems: tuple[_OutboxProblem, ...],
    errors: tuple[str, ...],
    migration_notices: tuple[str, ...],
    owner_manifest_problems: tuple[_OwnerManifestProblem, ...],
    owner_manifest_errors: tuple[str, ...],
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
        "problems": tuple(problem.to_data() for problem in problems),
        "error_count": len(errors),
        "errors": errors,
        "migration_notice_count": len(migration_notices),
        "migration_notices": migration_notices,
        "owner_manifest_problem_count": len(owner_manifest_problems),
        "owner_manifest_problems": tuple(
            problem.to_data() for problem in owner_manifest_problems
        ),
        "owner_manifest_error_count": len(owner_manifest_errors),
        "owner_manifest_errors": owner_manifest_errors,
        "thresholds": {
            "stalled_attempts": stalled_attempts,
            "stalled_age_seconds": stalled_age_seconds,
        },
        "remediation_command": _REMEDIATION_COMMAND,
        "retired_remediation_command": _RETIRED_REMEDIATION_COMMAND,
    }


def _owner_manifest_problems(
    context: DoctorContext,
    records: tuple[ProjectRecordWire, ...],
) -> tuple[tuple[_OwnerManifestProblem, ...], tuple[str, ...]]:
    enabled_projects = tuple(
        record.project_name
        for record in records
        if record.is_project and not is_disabled_project_lifecycle_state(record.state)
    )
    if not enabled_projects:
        return (), ()
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        return (), (f"owner manifest check skipped: owner identity unavailable: {exc}",)
    try:
        selection = resolve_sync_targets(
            enabled_projects,
            projects_root=context.sase_home / "projects",
        )
    except Exception as exc:  # noqa: BLE001 - doctor isolates target resolution.
        return (), (
            "owner manifest check skipped: could not resolve agents sidecar "
            f"targets: {type(exc).__name__}: {exc}",
        )

    problems: list[_OwnerManifestProblem] = []
    for target in selection.targets:
        try:
            read_owner_manifest(
                target.sidecar_path,
                owner,
                V2ProjectIdentity(target.project_key, target.project),
            )
        except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
            problems.append(
                _OwnerManifestProblem(
                    target.project_key,
                    target.project,
                    target.sidecar_path / owner_manifest_path(owner),
                    str(exc),
                )
            )
    target_errors = tuple(
        f"{outcome.project}: {outcome.error or outcome.skip_reason}"
        for outcome in selection.outcomes
        if outcome.error or outcome.skip_reason
    )
    return tuple(problems), target_errors


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
    return f"Run `{command}`."


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
