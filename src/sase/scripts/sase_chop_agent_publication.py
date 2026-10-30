#!/usr/bin/env python3
"""Scheduler job: drain durable agent, link, and Referenced By publication."""

from __future__ import annotations

from sase.agents_sync.publication_job import run_publication_job
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder


@builtin_chop("agent_publication")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    tick = run_publication_job()
    for diagnostic in tick.diagnostics:
        runtime.log.warning(f"[agent_publication] {diagnostic}")
    if tick.lock_busy:
        runtime.log.info(
            f"[agent_publication] {tick.lock_busy} project drain(s) deferred by a busy lock"
        )
    if tick.deferred_projects:
        runtime.log.info(
            f"[agent_publication] deferred {tick.deferred_projects} project(s) to a later tick"
        )
    result = runtime.emit_summary(
        {
            "projects": tick.projects,
            "hood_drained": tick.hood_drained,
            "link_drained": tick.link_drained,
            "referenced_by_drained": tick.referenced_by_drained,
            "active_remaining": tick.active_remaining,
            "lock_busy": tick.lock_busy,
            "deferred_projects": tick.deferred_projects,
            "errors": tick.errors,
        },
        reason="no_enabled_projects" if tick.projects == 0 else None,
    )
    if tick.errors:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("agent_publication")


if __name__ == "__main__":
    main()
