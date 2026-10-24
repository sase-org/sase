"""Agent publication outbox diagnostic for ``sase doctor``."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sase.agents_sync.publication_completion import stale_requested_revision_rows
from sase.agents_sync.publication_outbox import (
    AGENT_PUBLICATION_OUTBOX_FILENAME,
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    PUBLICATION_RETRY_COMMAND,
    AgentPublicationOutboxItem,
    configured_publication_max_attempts,
    publication_request_subject,
    snapshot_publication_document_from_path,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_agent_owner_identity
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.diagnostics import DiagnosticCheck
from sase.doctor._agent_publication import (
    OutboxProblem,
    OutboxProjectData,
    REMEDIATION_COMMAND,
    RETIRED_REMEDIATION_COMMAND,
    last_error_histogram,
    oldest_active_age_seconds,
    outbox_data,
    outbox_project_data,
    problem_for_item,
)
from sase.doctor.checks_agent_publication_sidecar import (
    outbox_sidecar_states,
    owner_manifest_problems,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

DEFAULT_PUBLICATION_STALLED_AGE_SECONDS = 24 * 60 * 60
_MAX_DETAIL_ROWS = 10
_MIGRATION_NEXT_STEP = (
    f"Obsolete publication requests were dropped while reading the outbox; run "
    f"`{PUBLICATION_RETRY_COMMAND}` to rewrite it at schema "
    f"{PUBLICATION_OUTBOX_SCHEMA_VERSION} and clear this notice."
)


def check_agent_publication_outbox(
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
            data=outbox_data(
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

    outboxes: list[OutboxProjectData] = []
    problems: list[OutboxProblem] = []
    errors: list[str] = []
    migration_notices: list[str] = []
    record_items: list[
        tuple[ProjectRecordWire, tuple[AgentPublicationOutboxItem, ...]]
    ] = []
    all_items: list[AgentPublicationOutboxItem] = []
    manifest_problems, owner_manifest_errors = owner_manifest_problems(
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
        all_items.extend(items)
        record_items.append((record, items))
        migration_notices.extend(
            f"{effective_project_name(record)}: {notice}" for notice in document.notices
        )

        project_problems: list[OutboxProblem] = []
        for item in items:
            problem = problem_for_item(
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
            outbox_project_data(record, path, items, project_problems_tuple)
        )
        problems.extend(project_problems_tuple)

    stale_entries = _stale_requested_revision_entries(context, tuple(record_items))
    stale_lines = tuple(detail for _, detail in stale_entries)
    stale_commands = tuple(
        dict.fromkeys(
            f"sase agent sync --repair-revisions -p {project_key} --apply"
            for project_key, _ in stale_entries
        )
    )
    data = outbox_data(
        projects_root=projects_root,
        records=records,
        outboxes=tuple(outboxes),
        problems=tuple(problems),
        errors=tuple(errors),
        migration_notices=tuple(migration_notices),
        owner_manifest_problems=manifest_problems,
        owner_manifest_errors=owner_manifest_errors,
        stalled_attempts=attempts_threshold,
        stalled_age_seconds=stalled_age_seconds,
        last_error_histogram=last_error_histogram(all_items),
        oldest_active_age_seconds=oldest_active_age_seconds(all_items, now=checked_at),
        sidecar_states=outbox_sidecar_states(
            context, tuple(outbox["project_key"] for outbox in outboxes)
        ),
        stale_requested_revision_count=len(stale_lines),
        stale_requested_revisions=stale_lines,
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

    if problems or manifest_problems or migration_notices or stale_lines:
        visible_problems = problems[:_MAX_DETAIL_ROWS]
        remaining_detail_rows = _MAX_DETAIL_ROWS - len(visible_problems)
        visible_manifest_problems = manifest_problems[:remaining_detail_rows]
        remaining_detail_rows -= len(visible_manifest_problems)
        visible_notices = tuple(migration_notices[:remaining_detail_rows])
        remaining_detail_rows -= len(visible_notices)
        visible_stale = tuple(stale_lines[:remaining_detail_rows])
        quarantined_count = sum(problem.quarantined for problem in problems)
        retired_count = sum(problem.retired for problem in problems)
        stalled_count = sum(problem.stalled for problem in problems)
        breakdown_parts = [
            *((f"{quarantined_count} quarantined",) if quarantined_count else ()),
            *((f"{retired_count} retired",) if retired_count else ()),
            *((f"{stalled_count} stalled",) if stalled_count else ()),
            *(
                (f"{len(manifest_problems)} unreadable owner manifest",)
                if manifest_problems
                else ()
            ),
            *(
                (f"{len(migration_notices)} obsolete request kind(s) dropped",)
                if migration_notices
                else ()
            ),
            *(
                (f"{len(stale_lines)} stale requested revision(s)",)
                if stale_lines
                else ()
            ),
        ]
        breakdown = ", ".join(breakdown_parts) or "needs attention"
        commands = tuple(
            dict.fromkeys(
                (
                    *(problem.remediation_command for problem in problems),
                    *(problem.remediation_command for problem in manifest_problems),
                )
            )
        )
        next_steps = (
            *(_next_step_for_command(command) for command in sorted(commands)),
            *((_MIGRATION_NEXT_STEP,) if migration_notices else ()),
            *(
                f"Run `{command}` to rekey that project's stale revisions."
                for command in stale_commands
            ),
        )
        attention_count = (
            len(problems)
            + len(manifest_problems)
            + len(migration_notices)
            + len(stale_lines)
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
                *visible_stale,
            ),
            next_steps=next_steps,
            data={
                **data,
                "details_truncated": (
                    len(problems) > len(visible_problems)
                    or len(manifest_problems) > len(visible_manifest_problems)
                    or len(migration_notices) > len(visible_notices)
                    or len(stale_lines) > len(visible_stale)
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


def _stale_requested_revision_entries(
    context: DoctorContext,
    record_items: tuple[
        tuple[ProjectRecordWire, tuple[AgentPublicationOutboxItem, ...]], ...
    ],
) -> tuple[tuple[str, str], ...]:
    """Return ``(project_key, detail)`` for rows the ack gate keeps refusing.

    Best-effort and read-only: any failure to resolve targets, identity, or
    snapshots degrades to no entries rather than failing doctor.
    """

    if not record_items:
        return ()
    try:
        selection = resolve_sync_targets(
            tuple(record.project_name for record, _ in record_items),
            projects_root=context.sase_home / "projects",
        )
    except Exception:  # noqa: BLE001 - doctor isolates target resolution.
        return ()
    try:
        owner = require_agent_owner_identity()
    except Exception:  # noqa: BLE001 - without identity there is no snapshot.
        return ()
    targets_by_key = {target.project_key: target for target in selection.targets}
    entries: list[tuple[str, str]] = []
    for record, items in record_items:
        target = targets_by_key.get(record.project_name)
        if target is None or not items:
            continue
        try:
            stale = stale_requested_revision_rows(target, items, owner)
        except Exception:  # noqa: BLE001 - one unreadable project is isolated.
            continue
        for item in stale:
            entries.append(
                (
                    target.project_key,
                    f"{effective_project_name(record)}: "
                    f"{publication_request_subject(item)} requests a revision "
                    "absent from its published run's commits; run "
                    f"`sase agent sync --repair-revisions "
                    f"-p {target.project_key} --apply`.",
                )
            )
    return tuple(entries)


def _next_step_for_command(command: str) -> str:
    if command == REMEDIATION_COMMAND:
        return (
            f"Run `{REMEDIATION_COMMAND}` to release quarantined requests and retry "
            "publication."
        )
    if command == RETIRED_REMEDIATION_COMMAND:
        return (
            f"Run `{RETIRED_REMEDIATION_COMMAND}` to drop retired requests that can "
            "never be published."
        )
    return f"Run `{command}`."
