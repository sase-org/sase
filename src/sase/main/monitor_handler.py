"""Handler for the 'sase monitor' CLI subcommand."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import NoReturn

from rich.console import Console

from sase.monitor import (
    MonitorAlreadyRunningError,
    MonitorError,
    MonitorLaneError,
    MonitorRecord,
    MonitorRefError,
    StartMonitorRequest,
    active_monitor_for_lane,
    caller_artifacts_dir,
    default_caller,
    durable_lane_for_record,
    list_monitors,
    maybe_handoff_monitor_from_agent,
    read_monitor_marker,
    resolve_caller_agent,
    resolve_lane,
    resolve_monitor_ref,
    short_monitor_id,
    start_monitor,
    stop_monitor,
    will_handoff_monitor_to_agent_runner,
)
from sase.monitor.start import (
    DEFAULT_NEXT_OUTPUT,
    DEFAULT_REASON,
    DEFAULT_TAIL_LINES,
    DEFAULT_TIMEOUT_SECONDS,
)
from sase.monitor_status import MONITOR_STATUS_MAX_CHARS, clamp_monitor_status

from .monitor_render import (
    empty_monitor_panel,
    monitor_detail,
    monitor_list_json,
    monitor_list_markdown,
    monitor_show_json,
    monitor_start_json,
    monitor_stop_json,
    monitor_table,
)

# Large enough to mean "every retained line" for a size-bounded monitor log.
_ALL_OUTPUT_LINES = 1_000_000
_KILLED_EXIT_CODE = 130
_FOLLOW_POLL_SECONDS = 0.5
_MISSING_START_STATUS = (
    "sase monitor start: -s/--start-status is required -- give the label shown while the "
    "command runs (present tense, e.g. TESTING), and pair it with -S/--stop-status (e.g. "
    "TESTED). Max 20 characters."
)
_MISSING_STOP_STATUS = (
    "sase monitor start: -S/--stop-status is required -- give the label shown when the "
    "command finishes (past tense, e.g. TESTED), and pair it with -s/--start-status (e.g. "
    "TESTING). Max 20 characters."
)
_MODEL_WITHOUT_NEXT = (
    "sase monitor start: -m/--model requires -n/--next -- no follow-up agent would "
    "consume the model selection"
)

_TIMEOUT_RE = re.compile(r"^(\d+(?:\.\d+)?)([smh]?)$")
_TIMEOUT_UNIT_SECONDS = {"s": 1.0, "m": 60.0, "h": 3600.0}


def handle_monitor_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch monitor subcommands."""
    subcommand = getattr(args, "monitor_subcommand", None)
    if subcommand in (None, "list"):
        sys.exit(_handle_monitor_list(args))
    if subcommand == "show":
        sys.exit(_handle_monitor_show(args))
    if subcommand == "start":
        sys.exit(_handle_monitor_start(args))
    if subcommand == "stop":
        sys.exit(_handle_monitor_stop(args))
    if subcommand == "_supervise":
        sys.exit(_handle_monitor_supervise(args))
    print("Usage: sase monitor {list,show,start,stop}", file=sys.stderr)
    sys.exit(1)


def _handle_monitor_list(args: argparse.Namespace) -> int:
    """Render monitor family members as a table, markdown, or JSON."""
    project = getattr(args, "project", None)
    agent = getattr(args, "agent", None)
    statuses = set(getattr(args, "status", None) or ())
    include_all = bool(getattr(args, "all", False))
    limit = getattr(args, "limit", None)
    fmt = (
        "json"
        if bool(getattr(args, "json", False))
        else getattr(args, "format", "table")
    )

    try:
        records = list_monitors(project=project)
    except Exception as exc:
        print(f"sase monitor list: cannot read monitors: {exc}", file=sys.stderr)
        return 1

    if agent:
        records = [record for record in records if record.lane == agent]
    if statuses:
        records = [record for record in records if record.monitor_state in statuses]
    elif not include_all:
        records = [record for record in records if not record.is_terminal]
    if limit is not None:
        records = records[: max(0, limit)]

    if fmt == "json":
        scope = {
            "all": include_all,
            "project": project,
            "agent": agent,
            "lane": agent,  # deprecated alias for "agent", kept for compatibility
            "status": sorted(statuses) or None,
        }
        json.dump(monitor_list_json(records, scope=scope), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if fmt == "markdown":
        sys.stdout.write(monitor_list_markdown(records))
        return 0

    console = Console()
    title = f"Monitors · {_scope_label(project=project, agent=agent, include_all=include_all)} ({len(records)})"
    if records:
        console.print(monitor_table(records, title=title))
    else:
        hint = (
            None
            if include_all
            else "No active monitors; pass -a/--all to include finished ones."
        )
        console.print(empty_monitor_panel(title, hint=hint))
    return 0


def _handle_monitor_show(args: argparse.Namespace) -> int:
    """Show one monitor's detail panel and captured output."""
    try:
        record = _resolve_ref(getattr(args, "monitor_id", ""))
    except MonitorRefError as exc:
        print(f"sase monitor show: {exc}", file=sys.stderr)
        return 2

    output_only = bool(getattr(args, "output_only", False))
    follow = bool(getattr(args, "follow", False))

    if getattr(args, "format", "markdown") == "json":
        # JSON is a snapshot, so following means "wait, then report the result".
        if follow and not record.is_terminal:
            try:
                record = _wait_for_monitor(record)
            except KeyboardInterrupt:
                return _KILLED_EXIT_CODE
        payload = monitor_show_json(record, output=_output_text(record, args))
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not output_only:
        Console().print(monitor_detail(record))

    if follow:
        try:
            return _follow_output(record, args)
        except KeyboardInterrupt:
            return _KILLED_EXIT_CODE

    output = _output_text(record, args)
    if output:
        sys.stdout.write(output if output.endswith("\n") else f"{output}\n")
    elif not output_only:
        print("(no output captured yet)")
    return 0


def _handle_monitor_start(args: argparse.Namespace) -> int:
    """Start a command as a monitor family member."""
    command = _start_command(args)
    if not command:
        print(
            "sase monitor start: command is required "
            "(pass `-- COMMAND` or the hidden `-c/--command` alias)",
            file=sys.stderr,
        )
        return 2
    reason = (getattr(args, "reason", None) or DEFAULT_REASON).strip()
    if not reason:
        print("sase monitor start: -r/--reason must not be empty", file=sys.stderr)
        return 2

    raw_start_status = getattr(args, "start_status", None)
    raw_stop_status = getattr(args, "stop_status", None)
    if raw_start_status is None:
        print(_MISSING_START_STATUS, file=sys.stderr)
        return 2
    if raw_stop_status is None:
        print(_MISSING_STOP_STATUS, file=sys.stderr)
        return 2

    next_action = getattr(args, "next", None)
    next_model = _optional_text(getattr(args, "model", None))
    if next_model and not _optional_text(next_action):
        print(_MODEL_WITHOUT_NEXT, file=sys.stderr)
        return 2

    try:
        raw_timeout = (
            getattr(args, "timeout", None) or f"{int(DEFAULT_TIMEOUT_SECONDS)}s"
        )
        timeout_seconds, timeout_label = _parse_timeout(raw_timeout)
        idle_timeout_seconds = 0.0
        idle_timeout_label: str | None = None
        raw_idle_timeout = getattr(args, "idle_timeout", None)
        if raw_idle_timeout:
            idle_timeout_seconds, idle_timeout_label = _parse_timeout(
                raw_idle_timeout,
                flag="-i/--idle-timeout",
            )
        start_status = _clamp_status_label(raw_start_status, flag="-s/--start-status")
        stop_status = _clamp_status_label(raw_stop_status, flag="-S/--stop-status")
    except ValueError as exc:
        print(f"sase monitor start: {exc}", file=sys.stderr)
        return 2

    explicit_agent = getattr(args, "agent", None)
    if explicit_agent:
        agent = explicit_agent
        exact_caller = False
    else:
        agent = default_caller()
        exact_caller = True
    if not agent:
        print(
            "sase monitor start: no agent given and SASE_AGENT_NAME is unset; "
            "pass -a/--agent explicitly",
            file=sys.stderr,
        )
        return 2

    cwd = _resolve_cwd(getattr(args, "cwd", None), agent, exact=exact_caller)
    project_name = _infer_project_name(str(cwd))
    if not project_name:
        print(
            f"sase monitor start: could not infer a project from cwd {cwd}",
            file=sys.stderr,
        )
        return 2

    request = StartMonitorRequest(
        command=command,
        reason=reason,
        timeout_seconds=timeout_seconds,
        cwd=str(cwd),
        project_name=project_name,
        lane=explicit_agent,
        label=getattr(args, "label", None),
        next_action=next_action,
        next_model=next_model,
        start_status=start_status,
        stop_status=stop_status,
        tail_lines=getattr(args, "tail_lines", None) or DEFAULT_TAIL_LINES,
        idle_timeout_seconds=idle_timeout_seconds,
        next_output=getattr(args, "next_output", None) or DEFAULT_NEXT_OUTPUT,
    )

    try:
        record = start_monitor(request)
    except (MonitorAlreadyRunningError, MonitorError) as exc:
        print(f"sase monitor start: {exc}", file=sys.stderr)
        return 1

    # kill_agent_runner_group() (invoked below, once handed off) never
    # returns, so every line of output must print before it -- including
    # the --json envelope, whose handed_off flag is decided the same way.
    handed_off = will_handoff_monitor_to_agent_runner()

    if bool(getattr(args, "json", False)):
        json.dump(
            monitor_start_json(record, handed_off=handed_off), sys.stdout, indent=2
        )
        sys.stdout.write("\n")
    else:
        short_id = short_monitor_id(record.monitor_id)
        print(f"Started monitor {short_id} ({record.monitor_id})")
        print(f"  member: {record.member_agent_name}")
        print(f"  timeout: {timeout_label}")
        if idle_timeout_label is not None:
            print(f"  idle timeout: {idle_timeout_label}")
        print(f"  sase monitor show {short_id} --follow")
        if handed_off:
            print(
                "\nThis is the last output before the agent runner is killed; "
                "the monitor keeps running."
            )
    sys.stdout.flush()

    maybe_handoff_monitor_from_agent(record)
    return 0


def _handle_monitor_stop(args: argparse.Namespace) -> int:
    """Stop one running monitor, resolving the same refs as ``monitor show``."""
    from sase.ops.commands.monitor import emit_monitor_stop_result

    try:
        record = _resolve_ref_or_active(getattr(args, "monitor_id", None))
    except MonitorRefError as exc:
        message = f"sase monitor stop: {exc}"
        emit_monitor_stop_result(
            success=False,
            message=message,
            payload={},
        )
        print(message, file=sys.stderr)
        return 2

    was_active = record.monitor_state == "running"
    result = stop_monitor(record)
    changed = was_active and result.monitor_state != "running"
    short_id = short_monitor_id(result.monitor_id)
    message = (
        f"Stopped monitor {short_id}."
        if changed
        else f"Monitor {short_id} is already {result.monitor_state}; nothing to do."
    )
    emit_monitor_stop_result(
        success=True,
        message=message,
        payload={
            "changed": changed,
            "monitor_id": result.monitor_id,
            "state": result.monitor_state,
        },
    )

    if bool(getattr(args, "json", False)):
        json.dump(monitor_stop_json(result, changed=changed), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(message)
    if changed and result.next_action:
        print("No follow-up agent was launched (stopped, not finished).")
    return 0


def _handle_monitor_supervise(args: argparse.Namespace) -> int:
    """Run the detached monitor supervisor for one artifacts dir."""
    from sase.monitor.supervise import run_supervisor

    return run_supervisor(args.artifacts_dir)


def _follow_output(record: MonitorRecord, args: argparse.Namespace) -> int:
    """Print the retained output, then stream new lines until terminal."""
    path = _output_path(record)
    retained = _output_text(record, args)
    if retained:
        sys.stdout.write(retained if retained.endswith("\n") else f"{retained}\n")

    try:
        offset = path.stat().st_size
    except OSError:
        offset = 0

    while True:
        current = read_monitor_marker(record.project_name, record.artifacts_dir)
        if current is None:
            print("sase monitor show: monitor record disappeared", file=sys.stderr)
            return 1
        new_text, offset = _read_new_text(path, offset)
        if new_text:
            sys.stdout.write(new_text)
            sys.stdout.flush()
        if current.is_terminal:
            return 0
        time.sleep(_FOLLOW_POLL_SECONDS)


def _wait_for_monitor(record: MonitorRecord) -> MonitorRecord:
    """Poll silently until *record*'s monitor reaches a terminal state."""
    while True:
        current = read_monitor_marker(record.project_name, record.artifacts_dir)
        if current is None:
            return record
        if current.is_terminal:
            return current
        time.sleep(_FOLLOW_POLL_SECONDS)


def _resolve_ref(raw_ref: str) -> MonitorRecord:
    records = list_monitors(project=None)
    return resolve_monitor_ref(raw_ref, records)


def _resolve_ref_or_active(raw_ref: str | None) -> MonitorRecord:
    if raw_ref:
        return _resolve_ref(raw_ref)
    caller = default_caller()
    if not caller:
        raise MonitorRefError(
            "no monitor id given and SASE_AGENT_NAME is unset; pass an explicit id"
        )
    project_name = _infer_project_name(str(Path.cwd()))
    if not project_name:
        raise MonitorRefError(f"agent {caller!r} has no active monitor")
    try:
        ctx = resolve_caller_agent(
            project_name, caller, artifacts_dir=caller_artifacts_dir()
        )
    except MonitorLaneError as exc:
        raise MonitorRefError(str(exc)) from exc
    lane = durable_lane_for_record(ctx.record, fallback=caller)
    active = active_monitor_for_lane(project_name, lane)
    if active is None:
        raise MonitorRefError(f"agent {lane!r} has no active monitor")
    return MonitorRecord.from_record(active)


def _resolve_cwd(explicit_cwd: str | None, agent: str, *, exact: bool) -> Path:
    if explicit_cwd:
        return Path(explicit_cwd).expanduser().resolve(strict=False)
    workspace = _agent_workspace_dir(agent, exact=exact)
    if workspace is not None:
        return workspace
    return Path.cwd()


def _agent_workspace_dir(agent: str, *, exact: bool) -> Path | None:
    guess_project = _infer_project_name(str(Path.cwd()))
    if not guess_project:
        return None
    try:
        ctx = (
            resolve_caller_agent(
                guess_project, agent, artifacts_dir=caller_artifacts_dir()
            )
            if exact
            else resolve_lane(guess_project, agent)
        )
    except MonitorLaneError:
        return None
    meta = ctx.record.agent_meta
    if meta is None or not meta.workspace_dir:
        return None
    return Path(meta.workspace_dir).expanduser()


def _infer_project_name(cwd: str) -> str | None:
    from sase.bead.project_name import infer_project_name_from_cwd

    return infer_project_name_from_cwd(cwd)


def _output_path(record: MonitorRecord) -> Path:
    if record.output_path:
        return Path(record.output_path)

    from sase.monitor.logs import monitor_log_path

    return monitor_log_path(record.artifacts_dir)


def _output_text(record: MonitorRecord, args: argparse.Namespace) -> str:
    from sase.monitor.logs import read_monitor_log_tail

    return read_monitor_log_tail(_output_path(record), _log_lines(args))


def _read_new_text(path: Path, offset: int) -> tuple[str, int]:
    try:
        current_size = path.stat().st_size
    except OSError:
        return "", offset
    if current_size < offset:
        offset = 0
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return "", offset
    if not chunk:
        return "", offset
    return chunk.decode("utf-8", errors="replace"), offset + len(chunk)


def _log_lines(args: argparse.Namespace) -> int:
    if bool(getattr(args, "all_lines", False)):
        return _ALL_OUTPUT_LINES
    return max(0, getattr(args, "log_lines", 200))


def _scope_label(*, project: str | None, agent: str | None, include_all: bool) -> str:
    parts = ["all projects" if project is None else f"project {project}"]
    if agent:
        parts.append(f"agent {agent}")
    parts.append("all" if include_all else "active")
    return ", ".join(parts)


def _parse_timeout(raw: str, *, flag: str = "-t/--timeout") -> tuple[float, str]:
    text = (raw or "").strip()
    match = _TIMEOUT_RE.match(text)
    if not match:
        raise ValueError(f"invalid {flag} value {raw!r}; use e.g. 90, 90s, 45m, 2h")
    value = float(match.group(1))
    unit = match.group(2) or "s"
    seconds = value * _TIMEOUT_UNIT_SECONDS[unit]
    if seconds <= 0:
        raise ValueError(f"{flag} must be greater than zero")
    return seconds, f"{text} ({_format_seconds(seconds)})"


def _format_seconds(seconds: float) -> str:
    if seconds == int(seconds):
        return f"{int(seconds)}s"
    return f"{seconds}s"


def _optional_text(value: object) -> str | None:
    """Return a stripped string, or ``None`` when *value* is blank."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _start_command(args: argparse.Namespace) -> str:
    """Resolve the command remainder, falling back to the hidden `-c` alias."""
    words = [str(part) for part in (getattr(args, "monitor_command_words", None) or [])]
    if words and words[0] == "--":
        words = words[1:]
    remainder = " ".join(words).strip()
    if remainder:
        return remainder
    return (getattr(args, "monitor_command", None) or "").strip()


def _clamp_status_label(value: str, *, flag: str) -> str:
    try:
        clamped = clamp_monitor_status(value)
    except ValueError as exc:
        raise ValueError(f"{flag}: {exc}") from exc
    if clamped != value.strip():
        print(
            f"sase monitor start: {flag} truncated to {MONITOR_STATUS_MAX_CHARS} "
            f"chars: {clamped!r}",
            file=sys.stderr,
        )
    return clamped


__all__ = [
    "handle_monitor_command",
]
