#!/usr/bin/env python3
"""Builtin chop that mirrors remote pull requests into local Patches."""

from __future__ import annotations

from datetime import UTC, datetime
import time

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.external_mirror.budget import LANE_CHOP_TIMEOUT_SECONDS
from sase.external_mirror.pr_sync import KIND, sync_external_pull_requests
from sase.external_mirror.report import MirrorReport
from sase.external_mirror.state import pr_mirror_state_dir, read_backoff_state
from sase.vcs_provider import get_vcs_provider

#: Derived from ``LANE_CHOP_TIMEOUT_SECONDS``, the ``external_mirror`` lane's
#: configured ``chop_timeout``, matching this chop's own explicit ``timeout``.
_WORK_BUDGET_SECONDS = 0.90 * LANE_CHOP_TIMEOUT_SECONDS


def _check_error(
    runtime: BuiltinChopRuntime,
    *,
    reason: str,
    detail: str,
) -> ChopResultBuilder:
    runtime.log.error(detail)
    result = runtime.emit_summary(
        MirrorReport(errors=1).summary_fields(),
        reason=reason,
    )
    result.status = "check_error"
    return result


@builtin_chop("external_pr_mirror")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    target = runtime.context.target or {}
    project = target.get("project")
    project_label = target.get("name")
    workspace_dir = target.get("workspace_dir")
    if not isinstance(project, str) or not project.strip():
        return _check_error(
            runtime,
            reason="missing_target_project",
            detail="external_pr_mirror requires a non-blank target.project",
        )
    if not isinstance(workspace_dir, str) or not workspace_dir.strip():
        label = project_label if isinstance(project_label, str) else "target project"
        return _check_error(
            runtime,
            reason="missing_target_workspace",
            detail=f"external_pr_mirror cannot resolve a workspace for {label}",
        )

    now = datetime.now(UTC)
    state_dir = pr_mirror_state_dir()
    backoff = read_backoff_state(state_dir, KIND)
    entry = backoff.get(project)
    if entry is not None and now < entry.next_attempt_at:
        return runtime.emit_summary(MirrorReport().summary_fields(), reason="backoff")

    provider = get_vcs_provider(workspace_dir.strip())
    report = sync_external_pull_requests(
        project_key=project.strip(),
        workspace_dir=workspace_dir.strip(),
        state_dir=state_dir,
        provider=provider,
        now=now,
        dry_run=runtime.context.dry_run,
        deadline=time.monotonic() + _WORK_BUDGET_SECONDS,
    )
    return runtime.emit_summary(report.summary_fields(), reason=report.reason())


def main() -> None:
    run_builtin_chop("external_pr_mirror")


if __name__ == "__main__":
    main()
