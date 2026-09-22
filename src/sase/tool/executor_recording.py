"""ToolRun begin/finish recording helpers for the executor.

Recording is fail-open: begin/finish failures never change the child result.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.config.tools import tool_project_identity
from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_begin, tool_run_finish
from sase.tool.argv import ResolvedToolArgv
from sase.tool.liveness import current_boot_id
from sase.tool.observe import fingerprints_mutated, inc_tool_metric
from sase.tool.ownership import ToolRunOwnership
from sase.telemetry.metrics import TOOL_RUN_RECORDING_ERRORS


def begin_tool_run(
    run_id: str,
    *,
    resolved: ResolvedToolArgv,
    ownership: ToolRunOwnership,
    events_path: Path | None,
    stdout_path: Path | None,
    stderr_path: Path | None,
) -> bool:
    wrapper_pid = os.getpid()
    identity = process_identity_token(wrapper_pid)
    boot_id, _, _ = identity.partition(":") if identity else ("", "", "")
    agent = (os.environ.get("SASE_AGENT_NAME") or "").strip() or (
        (os.environ.get("SASE_TOOL_RUN_AGENT") or "").strip() or None
    )
    request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "definition": resolved.definition,
        "extra_args": list(resolved.extra_args),
        "display_argv": list(resolved.display_argv),
        "project": _current_project_identity(),
        "agent": agent,
        "workspace": (os.environ.get("SASE_WORKSPACE_NUM") or "").strip() or None,
        "bead": (
            (
                os.environ.get("SASE_BEAD_ID") or os.environ.get("SASE_BEAD") or ""
            ).strip()
            or None
        ),
        "owner_kind": ownership.owner_kind,
        "owner_id": ownership.owner_id,
        "parent_run_id": ownership.parent_run_id,
        "wrapper_pid": wrapper_pid,
        "boot_id": boot_id or current_boot_id() or None,
        "process_start_identity": identity or None,
        "events_path": str(events_path) if events_path is not None else None,
        "log_stdout_path": str(stdout_path) if stdout_path is not None else None,
        "log_stderr_path": str(stderr_path) if stderr_path is not None else None,
        "commit_running": True,
    }
    if resolved.tool_name:
        request["tool_name"] = resolved.tool_name
    if resolved.private_argv is not None:
        request["private_argv"] = list(resolved.private_argv)
    try:
        started = tool_run_begin(request)
    except Exception:  # noqa: BLE001 - recording failure is fail-open.
        inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="begin")
        return False
    run = started.get("run") if isinstance(started, dict) else None
    ok = isinstance(run, dict) and str(run.get("state") or "") == "running"
    if not ok:
        inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="begin")
    return ok


def finish_tool_run(
    run_id: str,
    *,
    state: str,
    exit_code: int | None,
    duration_ms: int | None,
    signal_num: int | None = None,
    interruption_reason: str | None = None,
    child_pid: int | None = None,
    child_pgid: int | None = None,
    diagnostics: list[str] | None = None,
    fingerprint_before: dict[str, Any] | None = None,
    fingerprint_after: dict[str, Any] | None = None,
) -> bool:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "state": state,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }
    if signal_num is not None:
        payload["signal"] = signal_num
    if interruption_reason:
        payload["interruption_reason"] = interruption_reason
    if child_pid is not None:
        payload["child_pid"] = child_pid
    if child_pgid is not None:
        payload["child_pgid"] = child_pgid
    if diagnostics:
        payload["diagnostics"] = diagnostics
    if fingerprint_before is not None:
        payload["fingerprint_before"] = fingerprint_before
    if fingerprint_after is not None:
        payload["fingerprint_after"] = fingerprint_after
    mutated = fingerprints_mutated(fingerprint_before, fingerprint_after)
    if mutated is not None:
        payload["mutated_input"] = mutated
    try:
        tool_run_finish(payload)
    except Exception:  # noqa: BLE001 - never change the child result.
        return False
    return True


def _current_project_identity() -> str:
    try:
        return tool_project_identity()
    except Exception:  # noqa: BLE001 - attribution still works without a registry hit.
        return (
            os.environ.get("SASE_PROJECT")
            or os.environ.get("SASE_PROJECT_NAME")
            or "unknown"
        ).strip() or "unknown"


__all__ = ["begin_tool_run", "finish_tool_run"]
