#!/usr/bin/env python3
"""Builtin per-project external issue mirror chop.

Expands to one instance per enabled project via ``for_each: {source: projects}``
and shares its reconciliation path with ``sase bead sync-external``.
"""

from __future__ import annotations

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.external_mirror.issues import run_issue_mirror_for_project, summary_counters

#: Degradations that are surfaced as actionable failures, matching the
#: doctor-visible auth/rate-limit categories. Every other degradation
#: (backoff, unsupported provider, no canonical store) stays a quiet no_op.
_CHECK_ERROR_REASONS = frozenset({"auth_error", "rate_limited"})


def _check_error(
    runtime: BuiltinChopRuntime,
    *,
    reason: str,
    detail: str,
) -> ChopResultBuilder:
    runtime.log.error(detail)
    result = runtime.emit_summary(
        {
            "issues_seen": 0,
            "beads_created": 0,
            "notes_appended": 0,
            "conflicts": 0,
            "unmirrored": 0,
            "deferred": 0,
            "provider_calls": 0,
            "checkpoint_advanced": 0,
        },
        reason=reason,
    )
    result.status = "check_error"
    return result


@builtin_chop("external_issue_mirror")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    target = runtime.context.target or {}
    project_key = target.get("project")
    workspace_dir = target.get("workspace_dir")
    if not isinstance(workspace_dir, str) or not workspace_dir.strip():
        return _check_error(
            runtime,
            reason="missing_target_workspace",
            detail=(
                "external_issue_mirror requires a non-blank target.workspace_dir; "
                "configure for_each with the projects source"
            ),
        )
    if not isinstance(project_key, str) or not project_key.strip():
        return _check_error(
            runtime,
            reason="missing_target_project",
            detail=(
                "external_issue_mirror requires a non-blank target.project; "
                "configure for_each with the projects source"
            ),
        )
    display_name_raw = target.get("name")
    display_name = (
        display_name_raw.strip()
        if isinstance(display_name_raw, str) and display_name_raw.strip()
        else project_key.strip()
    )

    report = run_issue_mirror_for_project(
        project_key=project_key.strip(),
        display_name=display_name,
        workspace_dir=workspace_dir.strip(),
        dry_run=runtime.context.dry_run,
        source="chop",
    )

    if report.degraded:
        reason = report.degraded
    elif runtime.context.dry_run:
        reason = "dry_run"
    elif not (report.beads_created or report.notes_appended or report.deferred):
        reason = "no_changes"
    else:
        reason = None
    result = runtime.emit_summary(summary_counters(report), reason=reason)
    if report.degraded in _CHECK_ERROR_REASONS:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("external_issue_mirror")


if __name__ == "__main__":
    main()
