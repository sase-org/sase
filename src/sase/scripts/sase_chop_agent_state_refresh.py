#!/usr/bin/env python3
"""Scheduler job: bounded convergence for already-published run states.

One tick selects a single enabled project with a configured agents sidecar
and runs one default bounded repair window for the current owner. The
per-project cursor and bounded retry backoff persist under the job-state
lock, so live, missing, or contradictory rows never starve later rows and a
crash after push but before cursor persistence safely repeats the window. A
tick killed by the job timeout counts as a failed attempt (the project backs
off, keeps its cursor, and rotation continues), and a window that cannot
advance retries with backoff.
"""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.agent_state_refresh import (
    AgentStateRefreshSummary,
    run_agent_state_refresh,
)
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder


@builtin_chop("agent_state_refresh")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    summary: AgentStateRefreshSummary = run_agent_state_refresh(
        state_dir=Path(runtime.context.state_dir),
    )
    for diagnostic in summary.diagnostics:
        runtime.log.warning(f"[agent_state_refresh] {diagnostic}")
    if summary.selected_project:
        runtime.log.info(
            f"[agent_state_refresh] refreshed {summary.selected_project}: "
            f"examined={summary.examined} changed={summary.changed}"
        )
    result = runtime.emit_summary(
        {
            "projects": summary.projects,
            "examined": summary.examined,
            "changed": summary.changed,
            "already_current": summary.already_current,
            "live": summary.live,
            "unresolved": summary.unresolved,
            "withheld": summary.withheld,
            "failed": summary.failed,
            "errors": summary.errors,
        },
        reason=summary.reason,
    )
    if summary.errors:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("agent_state_refresh")


if __name__ == "__main__":
    main()
