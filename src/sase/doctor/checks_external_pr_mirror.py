"""Doctor check for the external PR mirror chop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sase.axe.state import lumberjack_state_dir
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.external_mirror.pr_sync import KIND
from sase.external_mirror.state import read_backoff_state, read_mirror_cursor
from sase.vcs_provider import supports_pull_requests

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_STALE_CURSOR_AFTER = timedelta(days=1)
_REPEATED_FAILURES = 3


def external_pr_mirror_check_specs(
    context: DoctorContext,
) -> tuple[CheckSpec, ...]:
    """Return external PR mirror doctor specs."""
    return (
        CheckSpec(
            id="axe.external_pr_mirror",
            group="axe",
            title="External PR mirror",
            runner=lambda: _check_external_pr_mirror(context),
        ),
    )


def _check_external_pr_mirror(context: DoctorContext) -> DiagnosticCheck:
    state_dir = lumberjack_state_dir("checks")
    now = datetime.now(UTC)
    backoff = read_backoff_state(state_dir, KIND)
    rows: list[dict[str, object]] = []
    details: list[str] = []
    errors = 0
    warnings = 0

    records = list_project_records(
        sase_projects_dir(),
        "enabled",
        include_home=False,
        projects_only=True,
    )
    for record in records:
        if not record.is_project or record.vcs_kind not in {"git", "gh"}:
            continue
        label = effective_project_name(record)
        workspace_dir = record.workspace_dir or ""
        supports_prs = False
        probe_error = ""
        if workspace_dir:
            try:
                supports_prs = supports_pull_requests(workspace_dir)
            except Exception as exc:  # noqa: BLE001 - structural probe failure.
                probe_error = str(exc)

        cursor = read_mirror_cursor(state_dir, KIND, record.project_name)
        failure = backoff.get(record.project_name)
        status: CheckStatus = "OK"
        reason = "ok"
        if not workspace_dir:
            status = "WARN"
            reason = "missing_workspace"
        elif probe_error:
            status = "WARN"
            reason = "probe_error"
        elif failure is not None and failure.failures >= _REPEATED_FAILURES:
            status = "ERROR"
            reason = "repeated_failures"
        elif supports_prs and _cursor_is_stale(cursor.last_updated_at, now):
            status = "WARN"
            reason = "stale_cursor"
        elif not supports_prs:
            reason = "pull_requests_unsupported"

        if status == "ERROR":
            errors += 1
        elif status == "WARN":
            warnings += 1

        row = {
            "project": record.project_name,
            "label": label,
            "status": status,
            "reason": reason,
            "workspace_dir": workspace_dir,
            "supports_pull_requests": supports_prs,
            "last_updated_at": (
                cursor.last_updated_at.isoformat()
                if cursor.last_updated_at is not None
                else None
            ),
            "failures": failure.failures if failure is not None else 0,
            "last_error": failure.last_error if failure is not None else "",
            "probe_error": probe_error,
        }
        rows.append(row)
        if status != "OK" or context.verbose:
            details.append(
                f"{status}: {label}: {reason}"
                + (f" ({failure.last_error})" if failure and failure.last_error else "")
            )

    if errors:
        status = "ERROR"
        summary = (
            f"external PR mirror recorded repeated failures in {errors} project(s)"
        )
    elif warnings:
        status = "WARN"
        summary = f"external PR mirror has {warnings} warning(s)"
    else:
        status = "OK"
        summary = f"external PR mirror state is healthy for {len(rows)} project(s)"

    return DiagnosticCheck(
        id="axe.external_pr_mirror",
        group="axe",
        status=status,
        title="External PR mirror",
        summary=summary,
        details=tuple(details[:10]),
        next_steps=(
            ("Run `sase patch sync-external --dry-run` from an authenticated shell.",)
            if status != "OK"
            else ()
        ),
        data={
            "project_count": len(rows),
            "errors": errors,
            "warnings": warnings,
            "projects": rows,
        },
    )


def _cursor_is_stale(last_updated_at: datetime | None, now: datetime) -> bool:
    if last_updated_at is None:
        return True
    return now - last_updated_at >= _STALE_CURSOR_AFTER


__all__ = ["external_pr_mirror_check_specs"]
