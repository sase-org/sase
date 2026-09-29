"""``sase tool show`` query presentation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import json
from pathlib import Path
import sys
from typing import Any

from sase.core.tool_run import tool_run_show
from sase.tool._query_shared import (
    detail_retention,
    logs_map,
    output_truncation,
    print_show,
    show_triage,
    write_bytes,
)
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.logs import (
    replay_retained_bytes,
    retained_log_rotated,
)
from sase.tool.owner import owner_retention
from sase.tool.query_follow import handle_follow
from sase.tool.stage_protocol import attach_timeline


@dataclass(frozen=True)
class ToolShowCliRequest:
    run_id: str
    json: bool
    logs: bool
    follow: bool = False


def handle_show(request: ToolShowCliRequest) -> int:
    """Render ``sase tool show RUN`` by exact id."""

    if request.json and request.logs:
        print("-j/--json and -l/--logs cannot be used together", file=sys.stderr)
        return 2
    if request.follow and request.logs:
        print("-F/--follow and -l/--logs cannot be used together", file=sys.stderr)
        return 2
    run_id = request.run_id.strip()
    if not run_id:
        print("Usage: sase tool show RUN", file=sys.stderr)
        return 2
    if request.follow:
        return handle_follow(request, run_id)
    reconcile_unsettled_tool_runs()
    try:
        envelope = tool_run_show(run_id)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1
    run = envelope.get("run")
    if not isinstance(run, dict):
        diagnostic = "; ".join(str(item) for item in envelope.get("diagnostics") or ())
        print(diagnostic or f"tool run {run_id} was not found", file=sys.stderr)
        return 2
    if request.logs:
        return _replay_logs(run)
    attach_timeline(envelope)
    envelope["triage"] = show_triage(run_id)
    envelope["output_truncation"] = output_truncation(run)
    envelope["detail_retention"] = detail_retention(run)
    envelope["owner_retention"] = owner_retention(run)
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    print_show(envelope)
    for diagnostic in envelope.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    retention = envelope["detail_retention"]
    if retention["detail_may_be_pruned"]:
        print(
            f"sase: stage and sample detail older than {retention['detail_days']} "
            "days is pruned by retention; it may be absent here",
            file=sys.stderr,
        )
    return 0


def _replay_logs(run: dict[str, Any]) -> int:
    logs = logs_map(run)
    stdout_path = logs.get("stdout_path")
    stderr_path = logs.get("stderr_path")
    if stdout_path or stderr_path:
        return _replay_tool_files(stdout_path, stderr_path, run)
    return _replay_owner_logs(run)


def _replay_tool_files(
    stdout_path: object, stderr_path: object, run: dict[str, Any]
) -> int:
    missing: list[str] = []
    truncated = output_truncation(run)
    replayed: list[str] = []
    for label, raw in (("stdout", stdout_path), ("stderr", stderr_path)):
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_file():
            missing.append(f"{label} log missing: {path}")
            continue
        try:
            empty = path.stat().st_size == 0
        except OSError:
            empty = False
        if retained_log_rotated(path):
            truncated.append(f"{label} retained log was rotated/truncated")
        dest = sys.stdout if label == "stdout" else sys.stderr
        replay_retained_bytes(path, partial(write_bytes, dest))
        if not empty:
            replayed.append(label)
    if replayed == ["stdout", "stderr"]:
        print(
            "sase: no total order between the retained stdout and stderr "
            "streams; order across them is not the child's write order",
            file=sys.stderr,
        )
    for message in (*truncated, *missing):
        print(f"sase: {message}", file=sys.stderr)
    return 0


def _replay_owner_logs(run: dict[str, Any]) -> int:
    kind = str(run.get("owner_kind") or "")
    owner_id = str(run.get("owner_id") or "")
    parent = str(run.get("parent_run_id") or "")
    if parent and not kind:
        print(
            f"sase: nested tool run output is owned by parent {parent}; "
            f"use sase tool show {parent} -l",
            file=sys.stderr,
        )
        return 0
    if kind == "proc" and owner_id:
        if not _replay_proc_log(owner_id):
            _replay_pruned_owner_log(run)
        return 0
    if kind == "monitor" and owner_id:
        if _replay_proc_log(owner_id):
            return 0
        return _replay_monitor_log(owner_id, str(run.get("project") or ""), run)
    print(
        "sase: retained stdout/stderr logs were not created for this run "
        "(enclosed or nested output is owned elsewhere)",
        file=sys.stderr,
    )
    return 0


def _replay_proc_log(proc_id: str) -> bool:
    try:
        from sase.procs.store import get_proc
    except Exception as exc:  # noqa: BLE001 - missing owner is reported.
        print(f"sase: proc owner log unavailable: {exc}", file=sys.stderr)
        return False
    proc = get_proc(proc_id)
    if proc is None:
        return False
    path = Path(proc.log_path)
    if not path.is_file():
        print(
            f"sase: proc owner log is missing or expired: {path}",
            file=sys.stderr,
        )
        return True
    print(
        "sase: owner log is combined stdout/stderr; no total stream order",
        file=sys.stderr,
    )
    replay_retained_bytes(path, lambda chunk: write_bytes(sys.stdout, chunk))
    return True


def _replay_pruned_owner_log(run: dict[str, Any]) -> None:
    """Replay the recorded owner log of a pruned owner, or say it is gone."""

    kind = str(run.get("owner_kind") or "owner")
    owner_id = str(run.get("owner_id") or "")
    recorded = logs_map(run).get("owner_log_path")
    if not recorded:
        print(
            f"sase: {kind} owner {owner_id} is no longer retained (pruned); "
            "its log was not recorded",
            file=sys.stderr,
        )
        return
    path = Path(str(recorded))
    if not path.is_file():
        print(
            f"sase: {kind} owner {owner_id} is no longer retained (pruned); "
            f"its log {path} is missing",
            file=sys.stderr,
        )
        return
    print(
        "sase: owner log is combined stdout/stderr; no total stream order",
        file=sys.stderr,
    )
    replay_retained_bytes(path, lambda chunk: write_bytes(sys.stdout, chunk))


def _replay_monitor_log(monitor_id: str, project: str, run: dict[str, Any]) -> int:
    try:
        from sase.tool.control import monitor_output_path
    except Exception as exc:  # noqa: BLE001 - missing owner is reported.
        print(f"sase: monitor owner log unavailable: {exc}", file=sys.stderr)
        return 0
    if project and not run.get("project"):
        run = {**run, "project": project}
    path = monitor_output_path(run, monitor_id)
    if path is None:
        _replay_pruned_owner_log(run)
        return 0
    if not path.is_file():
        print(
            f"sase: monitor owner log is missing or expired: {path}",
            file=sys.stderr,
        )
        return 0
    print(
        "sase: owner log is combined stdout/stderr; no total stream order",
        file=sys.stderr,
    )
    replay_retained_bytes(path, lambda chunk: write_bytes(sys.stdout, chunk))
    return 0


__all__ = [
    "ToolShowCliRequest",
    "handle_show",
]
