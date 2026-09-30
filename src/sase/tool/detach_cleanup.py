"""End-of-invocation cleanup for starter-scoped detached ToolRuns.

``invoke_agent`` calls :func:`stop_unjoined_detached_runs` in its ``finally``
so an unjoined detached run never outlives the provider invocation that
started it (contract rule 2, eager leg). A monitor handoff records its join
before it kills the runner, so an actively joined run is never touched here;
the worker watchdog covers whatever remains as a backstop.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


def joined_monitor_active(run: Mapping[str, Any]) -> str | None:
    """Return the joined monitor id when it names an active monitor."""

    join = run.get("join")
    if not isinstance(join, dict):
        return None
    if str(join.get("kind") or "") != "monitor":
        return None
    join_id = str(join.get("id") or "")
    if not join_id:
        return None
    try:
        from sase.tool.owner import observe_owner_fact

        fact = observe_owner_fact(
            {"launch_mode": "handoff", "owner_kind": "monitor", "owner_id": join_id}
        )
    except Exception:  # noqa: BLE001 - an unreadable owner is never active.
        return None
    if isinstance(fact, dict) and fact.get("state") == "active":
        return join_id
    return None


def _starter_matches(run_starter: object, current: Mapping[str, Any]) -> bool:
    """Return whether a run's starter names this runner's identity."""

    if not isinstance(run_starter, dict):
        return False
    for key in ("agent", "pid", "boot_id", "process_start_identity"):
        mine = current.get(key)
        theirs = run_starter.get(key)
        if mine is None and theirs is None:
            continue
        if str(mine or "") != str(theirs or ""):
            return False
    try:
        if int(run_starter.get("pid")) <= 0:  # type: ignore[arg-type]
            return False
    except (TypeError, ValueError):
        return False
    return True


def stop_unjoined_detached_runs(
    *,
    artifacts_dir: str | None = None,
    agent_name: str | None = None,
) -> int:
    """Stop this runner's unjoined detached runs; never raises.

    Candidates are unsettled runs attributed to this agent whose ``starter``
    matches this runner's identity and whose join is absent or names a
    monitor that is no longer active. Each stop is requested as
    ``requested_by: sase`` with the exact starter- or monitor-ended reason,
    routed through the shared owner path. Returns the number of runs
    stopped.
    """

    try:
        return _stop_unjoined_detached_runs(
            artifacts_dir=artifacts_dir, agent_name=agent_name
        )
    except Exception:  # noqa: BLE001 - cleanup never fails a turn.
        return 0


def _stop_unjoined_detached_runs(
    *,
    artifacts_dir: str | None,
    agent_name: str | None,
) -> int:
    from sase.core.tool_run import tool_run_briefs, tool_run_show
    from sase.tool.control_stop import stop_run_through_owner
    from sase.tool.starter import resolve_starter

    resolved_dir = (artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR") or "").strip()
    agent = (agent_name or os.environ.get("SASE_AGENT_NAME") or "").strip()
    if not resolved_dir or not agent:
        return 0
    resolution = resolve_starter(
        {**os.environ, "SASE_ARTIFACTS_DIR": resolved_dir, "SASE_AGENT_NAME": agent}
    )
    if not resolution.resolved or resolution.starter is None:
        return 0
    starter = resolution.starter
    try:
        briefs = tool_run_briefs(
            {"states": ["created", "running"], "agents": [agent], "limit": 500}
        )
    except Exception:  # noqa: BLE001 - an unreadable ledger stops nothing.
        return 0
    rows = getattr(briefs, "runs", None)
    if rows is None and isinstance(briefs, dict):
        rows = briefs.get("runs")
    if rows is None:
        return 0
    stopped = 0
    for row in rows:
        if isinstance(row, dict):
            run_id = str(row.get("run_id") or "")
        else:
            run_id = str(getattr(row, "run_id", "") or "")
        if not run_id:
            continue
        try:
            shown = tool_run_show(run_id)
        except Exception:  # noqa: BLE001 - skip runs that cannot be read.
            continue
        run = shown.get("run") if isinstance(shown, dict) else None
        if not isinstance(run, dict):
            continue
        if str(run.get("state") or "") not in ("created", "running"):
            continue
        if not _starter_matches(run.get("starter"), starter):
            continue
        if joined_monitor_active(run) is not None:
            continue
        join = run.get("join")
        if (
            isinstance(join, dict)
            and str(join.get("kind") or "") == "monitor"
            and str(join.get("id") or "")
        ):
            reason = f"joining monitor {join.get('id')} ended"
        else:
            reason = f"starter agent {agent} ended without joining"
        try:
            stop_run_through_owner(run_id, requested_by="sase", reason=reason)
        except Exception:  # noqa: BLE001 - one run never blocks the rest.
            continue
        stopped += 1
    return stopped


__all__ = ["joined_monitor_active", "stop_unjoined_detached_runs"]
