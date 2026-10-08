#!/usr/bin/env python3
"""Reap orphaned agent scopes whose runner died without cleaning up."""

from __future__ import annotations

from sase.agent.scope_sweep import reap_orphaned_agent_scopes
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.config._settings_system import get_agent_scope_teardown_enabled


@builtin_chop("orphan_agent_scope_reap")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    if not get_agent_scope_teardown_enabled():
        return runtime.emit_summary(
            {
                "scanned": 0,
                "live": 0,
                "skipped_young": 0,
                "spared_only": 0,
                "reaped_scopes": 0,
                "terminated": 0,
                "errors": 0,
            },
            reason="disabled",
        )
    result = reap_orphaned_agent_scopes(apply=True)
    for scope in result.reaped:
        agent = scope.agent_name or "unknown"
        detail = f"reaped {scope.unit} agent={agent} targets={scope.targets}"
        if scope.entries:
            detail += f" entries={'; '.join(scope.entries)}"
        runtime.log(detail, "cyan")
    return runtime.emit_summary(
        {
            "scanned": result.scanned,
            "live": result.live,
            "skipped_young": result.skipped_young,
            "spared_only": result.spared_only,
            "reaped_scopes": result.reaped_scopes,
            "terminated": result.terminated,
            "errors": result.errors,
        },
        reason="nothing_eligible" if not result.reaped else None,
    )


def main() -> None:
    run_builtin_chop("orphan_agent_scope_reap")


if __name__ == "__main__":
    main()
