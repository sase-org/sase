"""``sase tool runs`` and ``sase tool show`` query presentation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, TextIO, cast

from rich.console import Console
from rich.table import Table

from sase.config.tools import DEFAULT_TOOL_RUNS_DETAIL_DAYS, tool_project_identity
from sase.core.tool_run import tool_run_list, tool_run_show
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.logs import log_policy, read_truncation_messages, replay_retained_bytes
from sase.tool.owner import owner_retention
from sase.tool.render import (
    EMPTY,
    format_argv,
    format_duration_ms,
    format_state,
    format_tool_name,
)
from sase.tool.stage_protocol import attach_timeline, format_stage_progress


_RUN_STATES = frozenset(
    {
        "created",
        "failed",
        "interrupted",
        "lost",
        "running",
        "signaled",
        "succeeded",
    }
)
_MAX_LIMIT = 1000


class _ToolRunQueryError(ValueError):
    """User-facing query usage error (exit 2)."""


@dataclass(frozen=True)
class ToolRunsCliRequest:
    include_all: bool
    agent: str | None
    cursor: str | None
    json: bool
    limit: int
    state: str | None
    tool: str | None


@dataclass(frozen=True)
class ToolShowCliRequest:
    run_id: str
    json: bool
    logs: bool
    follow: bool = False


def handle_runs(request: ToolRunsCliRequest) -> int:
    """Render ``sase tool runs`` after reconciling unsettled wrappers."""

    try:
        limit = _validate_limit(request.limit)
        state = _validate_state(request.state)
    except _ToolRunQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    reconcile_unsettled_tool_runs()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "limit": limit,
    }
    if request.tool:
        payload["tool"] = request.tool
    if state:
        payload["state"] = state
    if request.agent:
        payload["agent"] = request.agent
    if request.cursor:
        payload["cursor"] = request.cursor
    if not request.include_all:
        payload["project"] = _project_identity()
    try:
        envelope = tool_run_list(payload)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    _print_runs_table(envelope)
    cursor = envelope.get("next_cursor")
    if cursor:
        print(f"next_cursor: {cursor}", file=sys.stderr)
    for diagnostic in envelope.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


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
        return _handle_follow(request, run_id)
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
    envelope["output_truncation"] = _output_truncation(run)
    envelope["detail_retention"] = _detail_retention(run)
    envelope["owner_retention"] = owner_retention(run)
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    _print_show(envelope)
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


def _handle_follow(request: ToolShowCliRequest, run_id: str) -> int:
    """Stream the output of record until the run settles, then summarize.

    Ctrl-C detaches the viewer and exits 130; the run continues.
    ``-F -j`` waits, then prints the final JSON envelope instead of the
    human summary.
    """

    from sase.tool.control import output_paths_for_run, wait_for_settlement
    from sase.tool.control import UnknownRunError as _ControlUnknownRun

    try:
        first = tool_run_show(run_id)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1
    if not isinstance(first.get("run"), dict):
        diagnostic = "; ".join(str(item) for item in first.get("diagnostics") or ())
        print(diagnostic or f"tool run {run_id} was not found", file=sys.stderr)
        return 2
    offsets: dict[str, int] = {}
    notified: list[bool] = []
    ingestor = _follow_ingestor(first.get("run"))
    _stream_output_paths(first.get("run"), offsets)
    _notice_unretained_output(first["run"], notified)
    if ingestor is not None:
        for line in ingestor.tick():
            print(line, file=sys.stderr)

    def _on_poll(envelope: dict[str, Any]) -> None:
        run = envelope.get("run")
        if not isinstance(run, dict):
            return
        _stream_output_paths(run, offsets)
        nonlocal ingestor
        fresh = _follow_ingestor(run)
        if fresh is not None and (ingestor is None or fresh.path != ingestor.path):
            ingestor = fresh
        if ingestor is not None:
            for line in ingestor.tick():
                print(line, file=sys.stderr)

    try:
        final = wait_for_settlement(run_id, on_poll=_on_poll)
    except _ControlUnknownRun as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "sase tool show: detached; the run continues",
            file=sys.stderr,
        )
        return 130
    if final is None:  # No deadline is ever passed here; the loop ends settled.
        return 1
    run = final.get("run")
    if not isinstance(run, dict):
        print(f"tool run {run_id} was not found", file=sys.stderr)
        return 2
    _stream_output_paths(run, offsets)
    if ingestor is not None:
        for line in ingestor.tick():
            print(line, file=sys.stderr)
    _notice_unretained_output(run, notified)
    attach_timeline(final)
    final["output_truncation"] = _output_truncation(run)
    final["detail_retention"] = _detail_retention(run)
    final["owner_retention"] = owner_retention(run)
    if request.json:
        print(json.dumps(final, indent=2, sort_keys=True))
        return 0
    _print_show(final)
    for diagnostic in final.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _notice_unretained_output(run: dict[str, Any], notified: list[bool]) -> None:
    """Say once that an owner-bound run has no output of record to stream.

    A run still starting can lack its log for a moment, so the notice waits
    for a settled run or a pruned owner; the final call covers the rest.
    """

    if notified:
        return
    retention = owner_retention(run)
    if retention["owner"] == "none" or retention["log"] == "retained":
        return
    settled = str(run.get("state") or "") not in {"created", "running"}
    if not (settled or retention["owner"] == "pruned"):
        return
    notified.append(True)
    print(_unretained_message(run, retention), file=sys.stderr)


def _unretained_message(run: dict[str, Any], retention: dict[str, Any]) -> str:
    kind = str(run.get("owner_kind") or "owner")
    owner_id = str(run.get("owner_id") or "")
    path = retention.get("log_path")
    if retention["owner"] == "pruned":
        detail = (
            f"; its log {path} is missing" if path else "; its log was not recorded"
        )
        return f"sase: {kind} owner {owner_id} is no longer retained (pruned){detail}"
    if path:
        return f"sase: {kind} owner {owner_id} log {path} is missing or expired"
    return f"sase: {kind} owner {owner_id} did not record an output log"


def _follow_ingestor(run: object):  # type: ignore[no-untyped-def]
    if not isinstance(run, dict):
        return None
    logs = run.get("logs")
    raw = logs.get("events_path") if isinstance(logs, dict) else None
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_file():
        return None
    from sase.tool.stage_protocol import StageIngestor

    return StageIngestor(path=path, run_id=str(run.get("run_id") or ""))


def _stream_output_paths(run: object, offsets: dict[str, int]) -> None:
    """Print bytes appended to the output of record since the last poll."""

    if not isinstance(run, dict):
        return
    from sase.tool.control import output_paths_for_run

    for path in output_paths_for_run(run):
        key = str(path)
        start = offsets.get(key, 0)
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
        except OSError:
            continue
        if size < start:
            start = 0
        if size == start:
            continue
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                chunk = handle.read()
        except OSError:
            continue
        offsets[key] = size
        if chunk:
            _write_bytes(sys.stdout, chunk)


def _replay_logs(run: dict[str, Any]) -> int:
    logs = _logs_map(run)
    stdout_path = logs.get("stdout_path")
    stderr_path = logs.get("stderr_path")
    if stdout_path or stderr_path:
        return _replay_tool_files(stdout_path, stderr_path, run)
    return _replay_owner_logs(run)


def _replay_tool_files(
    stdout_path: object, stderr_path: object, run: dict[str, Any]
) -> int:
    missing: list[str] = []
    truncated = _output_truncation(run)
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
        if path.with_name(f"{path.name}.1").exists():
            truncated.append(f"{label} retained log was rotated/truncated")
        dest = sys.stdout if label == "stdout" else sys.stderr
        replay_retained_bytes(path, partial(_write_bytes, dest))
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


def _detail_retention(run: dict[str, Any]) -> dict[str, Any]:
    """State the detail horizon; a run older than it may have lost its detail."""

    days = int(log_policy().get("detail_days") or DEFAULT_TOOL_RUNS_DETAIL_DAYS)
    settled = run.get("settled_ts")
    old = type(settled) is int and time.time() - settled > days * 86400
    return {"detail_days": days, "detail_may_be_pruned": bool(old)}


def _output_truncation(run: dict[str, Any]) -> list[str]:
    return read_truncation_messages(
        _logs_map(run).get("events_path"), str(run.get("run_id") or "")
    )


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
    replay_retained_bytes(path, lambda chunk: _write_bytes(sys.stdout, chunk))
    return True


def _replay_pruned_owner_log(run: dict[str, Any]) -> None:
    """Replay the recorded owner log of a pruned owner, or say it is gone."""

    kind = str(run.get("owner_kind") or "owner")
    owner_id = str(run.get("owner_id") or "")
    recorded = _logs_map(run).get("owner_log_path")
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
    replay_retained_bytes(path, lambda chunk: _write_bytes(sys.stdout, chunk))


def _replay_monitor_log(monitor_id: str, project: str, run: dict[str, Any]) -> int:
    try:
        from sase.monitor.logs import monitor_log_path
        from sase.monitor.store import list_monitors, resolve_monitor_ref
    except Exception as exc:  # noqa: BLE001 - missing owner is reported.
        print(f"sase: monitor owner log unavailable: {exc}", file=sys.stderr)
        return 0
    try:
        records = list_monitors(project=project or None)
        record = resolve_monitor_ref(monitor_id, records)
    except Exception:  # noqa: BLE001 - expired owners fall back to the recorded log.
        _replay_pruned_owner_log(run)
        return 0
    path = Path(record.output_path or monitor_log_path(record.artifacts_dir))
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
    replay_retained_bytes(path, lambda chunk: _write_bytes(sys.stdout, chunk))
    return 0


def _print_runs_table(envelope: dict[str, Any]) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID")
    table.add_column("TOOL")
    table.add_column("STATE")
    table.add_column("DURATION")
    table.add_column("ARGV")
    runs = envelope.get("runs") or ()
    if not runs:
        table.add_row(EMPTY, EMPTY, EMPTY, EMPTY, "no tool runs")
    for run in runs:
        if not isinstance(run, dict):
            continue
        table.add_row(
            str(run.get("run_id") or EMPTY),
            format_tool_name(run),
            _format_runs_state(run),
            format_duration_ms(
                run.get("duration_ms") if type(run.get("duration_ms")) is int else None
            ),
            format_argv(run),
        )
    console.print(table)


def _format_runs_state(run: dict[str, Any]) -> str:
    """Render the STATE cell, marking hand-offs and starting runs."""

    state = format_state(run)
    markers: list[str] = []
    if str(run.get("launch_mode") or "") == "handoff":
        markers.append("handoff")
    if str(run.get("state") or "") == "created":
        markers.append("starting")
    if markers:
        return f"{state} ({', '.join(markers)})"
    return state


def _print_show(envelope: dict[str, Any]) -> None:
    run = envelope.get("run")
    if not isinstance(run, dict):
        return
    logs = _logs_map(run)
    retention_line = _format_owner_retention(run, envelope.get("owner_retention"))
    lines = [
        f"RUN       {run.get('run_id') or EMPTY}",
        f"TOOL      {format_tool_name(run)}",
        f"STATE     {format_state(run)}",
        f"ARGV      {format_argv(run)}",
        f"PROJECT   {run.get('project') or EMPTY}",
        f"LAUNCH    {run.get('launch_mode') or 'foreground'}",
        f"OWNER     {_format_owner(run)}",
        f"PARENT    {run.get('parent_run_id') or EMPTY}",
        f"DURATION  {format_duration_ms(run.get('duration_ms') if type(run.get('duration_ms')) is int else None)}",
        f"EXIT      {run.get('exit_code') if run.get('exit_code') is not None else EMPTY}",
        f"SIGNAL    {run.get('signal') if run.get('signal') is not None else EMPTY}",
        f"CAUSE     {run.get('terminal_cause') or EMPTY}",
        f"SETTLED   {run.get('settled_by') or EMPTY}",
        f"STOP      {_format_stop_request(run)}",
        f"LOST      {run.get('lost_reason') or EMPTY}",
        f"STDOUT    {logs.get('stdout_path') or EMPTY}",
        f"STDERR    {logs.get('stderr_path') or EMPTY}",
        f"EVENTS    {logs.get('events_path') or EMPTY}",
        f"OWNERLOG  {logs.get('owner_log_path') or EMPTY}",
        *([retention_line] if retention_line is not None else []),
        f"EVIDENCE  {_format_evidence(run)}",
        f"MUTATED   {_format_optional_bool(run.get('mutated_input'))}",
        f"DIRTY     {_dirty_count(run.get('fingerprint_before'))} -> {_dirty_count(run.get('fingerprint_after'))}",
        f"TOOLCHAIN {_format_toolchain(run)}",
        f"SAMPLES   {len(envelope.get('samples') or ())}",
    ]
    diagnostics = run.get("diagnostics") or ()
    if diagnostics:
        lines.append("DIAG")
        for diagnostic in diagnostics:
            lines.append(f"  {diagnostic}")
    if envelope.get("stages"):
        unattributed = envelope.get("unattributed_ms")
        unattr_line = (
            "UNATTRIB  "
            f"{format_duration_ms(unattributed if type(unattributed) is int else None)}"
        )
        if envelope.get("unattributed_incomplete"):
            unattr_line += "  incomplete"
        lines.append(unattr_line)
    print("\n".join(lines))
    stages = envelope.get("stages") or ()
    if stages:
        print("STAGES")
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            print(f"  {format_stage_progress(stage)}")
    samples = envelope.get("samples") or ()
    if samples:
        print("SAMPLES")
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            print(f"  {_format_sample(sample)}")


def _format_owner_retention(run: dict[str, Any], retention: object) -> str | None:
    """Render ``OWNERRET`` for an owner-bound run; ``None`` when unowned."""

    if not isinstance(retention, dict) or retention.get("owner") in (None, "none"):
        return None
    owner = retention["owner"]
    log = retention.get("log")
    if log == "retained":
        log_text = "log retained"
    elif log == "missing":
        log_text = "log not retained" if owner == "pruned" else "log missing"
    else:
        log_text = "log not recorded"
    return (
        f"OWNERRET  {run.get('owner_kind') or EMPTY} "
        f"{run.get('owner_id') or EMPTY}: {owner}; {log_text}"
    )


def _format_evidence(run: dict[str, Any]) -> str:
    evidence = run.get("evidence_completeness")
    if not isinstance(evidence, dict):
        return EMPTY
    if evidence.get("complete"):
        return "complete"
    missing = evidence.get("missing") or ()
    detail = ", ".join(str(item) for item in missing if item)
    if detail:
        return f"incomplete ({detail})"
    return "incomplete"


def _format_optional_bool(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return EMPTY


def _dirty_count(fingerprint: object) -> int:
    if not isinstance(fingerprint, dict):
        return 0
    total = 0
    for repo in fingerprint.get("repos") or ():
        if isinstance(repo, dict):
            total += len(repo.get("dirty_paths") or ())
    return total


def _format_toolchain(run: dict[str, Any]) -> str:
    fingerprint = run.get("fingerprint_after") or run.get("fingerprint_before")
    if not isinstance(fingerprint, dict):
        return EMPTY
    toolchain = fingerprint.get("toolchain") or {}
    if not isinstance(toolchain, dict) or not toolchain:
        return EMPTY
    parts: list[str] = []
    for name, probe in toolchain.items():
        if not isinstance(probe, dict):
            continue
        if probe.get("incomplete"):
            parts.append(f"{name}=incomplete")
            continue
        output = str(probe.get("output") or "").strip().splitlines()
        parts.append(f"{name}={output[0] if output else EMPTY}")
    return "  ".join(parts) or EMPTY


def _format_sample(sample: dict[str, Any]) -> str:
    elapsed = sample.get("elapsed_ms")
    load = sample.get("loadavg_1")
    psi = sample.get("psi_cpu_some")
    load_text = f"{load:.2f}" if isinstance(load, (int, float)) else EMPTY
    psi_text = f"{psi:.2f}" if isinstance(psi, (int, float)) else EMPTY
    elapsed_text = format_duration_ms(elapsed) if type(elapsed) is int else EMPTY
    return f"{elapsed_text}  load1={load_text}  psi_cpu={psi_text}"


def _logs_map(run: dict[str, Any]) -> dict[str, Any]:
    raw = run.get("logs")
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}


def _format_owner(run: dict[str, Any]) -> str:
    kind = run.get("owner_kind")
    owner_id = run.get("owner_id")
    if kind and owner_id:
        return f"{kind}:{owner_id}"
    return EMPTY


def _format_stop_request(run: dict[str, Any]) -> str:
    stop = run.get("stop_request")
    if not isinstance(stop, dict):
        return EMPTY
    by = str(stop.get("requested_by") or "").strip()
    return f"requested by {by}" if by else "requested"


def _validate_limit(limit: int) -> int:
    if limit < 1 or limit > _MAX_LIMIT:
        raise _ToolRunQueryError(f"-n/--limit must be 1..={_MAX_LIMIT}")
    return limit


def _validate_state(state: str | None) -> str | None:
    if state is None:
        return None
    if state not in _RUN_STATES:
        allowed = ", ".join(sorted(_RUN_STATES))
        raise _ToolRunQueryError(f"unknown state {state!r}; expected one of {allowed}")
    return state


def _project_identity() -> str:
    try:
        return tool_project_identity()
    except Exception:  # noqa: BLE001 - listing still works without a registry hit.
        return (
            os.environ.get("SASE_PROJECT")
            or os.environ.get("SASE_PROJECT_NAME")
            or "unknown"
        ).strip() or "unknown"


def _write_bytes(stream: TextIO, data: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
        return
    stream.write(data.decode("utf-8", "replace"))
    stream.flush()


__all__ = [
    "ToolRunsCliRequest",
    "ToolShowCliRequest",
    "handle_runs",
    "handle_show",
]
