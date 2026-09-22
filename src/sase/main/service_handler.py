"""Handlers for ``sase service`` and ``sase service proc`` commands."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, NoReturn

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sase.procs import ProcSubmitError
from sase.procs.oneshot import submit_oneshot
from sase.service.config import ServiceConfigError, load_service_config
from sase.service.control import (
    current_service_status,
    latest_service_log_lines,
    persisted_or_current_status,
    restart_service_host,
    start_service_host,
    stop_service_host,
)
from sase.service.host import run_service_host
from sase.service.env import load_service_environment
from sase.service.paths import service_host_log_path, service_proc_output_log_path
from sase.service.actions import (
    ServiceProcActionError,
    ServiceProcActionOutcome,
    disable_service_proc,
    enable_service_proc,
    restart_service_proc,
    start_service_proc,
    stop_service_proc,
    wait_for_service_proc_request,
)
from sase.service.platform import (
    ServicePlatformPlan,
    apply_service_init,
    apply_service_uninstall,
    service_init_plan,
    service_uninstall_plan,
)


def handle_service_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch top-level service commands."""
    try:
        if getattr(args, "service_subcommand", None) == "run":
            load_service_environment(override_existing=True)
        code = _handle_service_command(args)
    except ServiceConfigError as exc:
        print(str(exc), file=sys.stderr)
        code = 2
    except ServiceProcActionError as exc:
        print(str(exc), file=sys.stderr)
        code = 2
    sys.exit(code)


def _handle_service_command(args: argparse.Namespace) -> int:
    subcommand = getattr(args, "service_subcommand", None) or "status"
    if subcommand == "init":
        return _handle_service_init(args)
    if subcommand == "logs":
        return _handle_service_logs(args)
    if subcommand == "proc":
        return _handle_service_proc(args)
    if subcommand == "restart":
        return _print_action(restart_service_host(), args)
    if subcommand == "run":
        return run_service_host()
    if subcommand == "start":
        return _print_action(start_service_host(), args)
    if subcommand == "status":
        return _handle_service_status(args)
    if subcommand == "stop":
        return _print_action(stop_service_host(), args)
    if subcommand == "uninstall":
        return _handle_service_uninstall(args)
    print(
        "Usage: sase service {init,logs,proc,restart,run,start,status,stop,uninstall}",
        file=sys.stderr,
    )
    return 2


def _handle_service_status(args: argparse.Namespace) -> int:
    snapshot = persisted_or_current_status()
    if bool(getattr(args, "json", False)):
        json.dump(snapshot.to_wire(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    console = Console()
    console.print(f"[bold]Service host:[/bold] {snapshot.host.summary}")
    if snapshot.host.platform_unit:
        console.print(f"[dim]Native unit:[/dim] {snapshot.host.platform_unit}")
    if snapshot.host.error:
        console.print(f"[bold red]Host error:[/bold red] {snapshot.host.error}")
    table = Table(title="Service procs")
    table.add_column("Name")
    table.add_column("Desired")
    table.add_column("State")
    table.add_column("Restarts")
    table.add_column("Last exit")
    table.add_column("Summary")
    for proc in snapshot.procs:
        table.add_row(
            proc.name,
            proc.desired,
            _proc_state_text(proc),
            str(proc.restarts),
            _last_exit_cell(proc),
            proc.summary,
        )
    console.print(table)
    for diagnostic in snapshot.diagnostics:
        console.print(f"[yellow]{diagnostic}[/yellow]")
    plan = service_init_plan(force=True)
    for diagnostic in (*plan.blockers, *plan.warnings):
        console.print(f"[yellow]{diagnostic}[/yellow]")
    return 0 if snapshot.host.state in {"running", "starting"} else 1


def _handle_service_init(args: argparse.Namespace) -> int:
    force = bool(getattr(args, "force", False))
    allow_agent_env = bool(getattr(args, "allow_agent_env", False))
    if bool(getattr(args, "yes", False)):
        result = apply_service_init(force=force, allow_agent_env=allow_agent_env)
        _print_platform_plan(result.plan, show_diff=False)
        print(result.message)
        if result.ok:
            return 0
        if "allow-agent-env" in result.message:
            return 2
        return 1
    plan = service_init_plan(force=force)
    _print_platform_plan(plan, show_diff=bool(getattr(args, "diff", False)))
    if bool(getattr(args, "check", False)):
        return 0 if plan.current else 1
    if plan.current:
        return 0
    print("Run `sase service init --yes` to apply these changes.")
    return 1


def _handle_service_uninstall(args: argparse.Namespace) -> int:
    force = bool(getattr(args, "force", False))
    if bool(getattr(args, "yes", False)):
        result = apply_service_uninstall(force=force)
        _print_platform_plan(result.plan, show_diff=False)
        print(result.message)
        return 0 if result.ok else 1
    plan = service_uninstall_plan(force=force)
    _print_platform_plan(plan, show_diff=bool(getattr(args, "diff", False)))
    if bool(getattr(args, "check", False)):
        return 0 if plan.current else 1
    if plan.current:
        return 0
    print("Run `sase service uninstall --yes` to apply these changes.")
    return 1


def _print_platform_plan(plan: ServicePlatformPlan | None, *, show_diff: bool) -> None:
    if plan is None:
        return
    console = Console()
    console.print(f"[bold]Service platform:[/bold] {plan.status}")
    console.print(f"  unit: {plan.definition.identity}")
    console.print(f"  definition: {plan.definition.definition_path}")
    console.print(f"  environment: {plan.definition.env_path}")
    if plan.actions:
        console.print("Actions:", style="bold")
        for action in plan.actions:
            console.print(f"  - {action}")
    if plan.blockers:
        console.print("Blockers:", style="bold red")
        for blocker in plan.blockers:
            console.print(f"  - {blocker}", style="red")
    if plan.warnings:
        console.print("Warnings:", style="bold yellow")
        for warning in plan.warnings:
            console.print(f"  - {warning}", style="yellow")
    if show_diff and plan.diff:
        console.print(plan.diff)


def _handle_service_logs(args: argparse.Namespace) -> int:
    text = latest_service_log_lines(
        service_host_log_path(), lines=int(getattr(args, "lines", 200))
    )
    if text:
        print(text)
    return 0


def _handle_service_proc(args: argparse.Namespace) -> int:
    subcommand = getattr(args, "service_proc_subcommand", None) or "list"
    if subcommand == "disable":
        return _handle_proc_enablement(args, enabled=False)
    if subcommand == "enable":
        return _handle_proc_enablement(args, enabled=True)
    if subcommand == "list":
        return _handle_proc_list(args)
    if subcommand == "logs":
        return _handle_proc_logs(args)
    if subcommand == "restart":
        return handle_service_proc_restart(args)
    if subcommand == "run":
        return _handle_proc_run(args)
    if subcommand == "show":
        return handle_service_proc_show(args)
    if subcommand == "start":
        return handle_service_proc_start(args)
    if subcommand == "stop":
        return _handle_proc_stop(args)
    print(
        "Usage: sase service proc {disable,enable,list,logs,restart,run,show,start,stop}",
        file=sys.stderr,
    )
    return 2


def _handle_proc_list(args: argparse.Namespace) -> int:
    snapshot = current_service_status()
    if bool(getattr(args, "json", False)):
        json.dump(
            {
                "schema_version": snapshot.schema_version,
                "procs": [proc.to_wire() for proc in snapshot.procs],
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0
    table = Table(title="Service procs")
    table.add_column("Name")
    table.add_column("Enabled")
    table.add_column("Desired")
    table.add_column("State")
    table.add_column("Restarts")
    table.add_column("Last exit")
    table.add_column("Summary")
    for proc in snapshot.procs:
        table.add_row(
            proc.name,
            proc.enablement.summary,
            proc.desired,
            _proc_state_text(proc),
            str(proc.restarts),
            _last_exit_cell(proc),
            proc.summary,
        )
    Console().print(table)
    return 0


def handle_service_proc_show(args: argparse.Namespace) -> int:
    name = str(args.name)
    snapshot = current_service_status()
    proc = next((item for item in snapshot.procs if item.name == name), None)
    if proc is None:
        print(f"sase service proc show: unknown service proc {name!r}", file=sys.stderr)
        return 2
    if bool(getattr(args, "json", False)):
        json.dump(proc.to_wire(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    console = Console()
    console.print(f"[bold]{proc.name}[/bold] · {proc.summary}")
    console.print(f"  source: {proc.source} ({proc.declared_by})")
    console.print(f"  enabled: {proc.enablement.summary}")
    console.print(f"  desired: {proc.desired}")
    console.print(_proc_state_line(proc))
    if proc.description:
        console.print(f"  description: {proc.description}")
    if proc.started_at is not None:
        console.print(
            f"  uptime: {_format_duration(time.time() - proc.started_at)}"
            f" (pid {proc.pid})"
            if proc.pid is not None
            else f"  uptime: {_format_duration(time.time() - proc.started_at)}"
        )
    elif proc.pid is not None:
        console.print(f"  pid: {proc.pid}")
    console.print(f"  restarts: {proc.restarts}")
    last_exit = _format_last_exit(proc)
    if last_exit is not None:
        console.print(f"  last exit: {last_exit}")
    restart_reason = _restart_reason_text(proc)
    if restart_reason is not None:
        console.print(f"  restart: {restart_reason}")
    stop_provenance = _stop_provenance_text(proc)
    if stop_provenance is not None:
        console.print(f"  stopped by: {stop_provenance}")
    pending_request = _pending_request_text(proc)
    if pending_request is not None:
        console.print(f"  request: {pending_request}")
    if proc.launcher_summary:
        console.print(f"  launcher: {proc.launcher_summary}")
    if proc.log_path:
        console.print(f"  log: {proc.log_path}")
    if proc.unavailable_reason:
        console.print(f"  unavailable: {proc.unavailable_reason}")
    return 0


def _proc_state_text(proc: Any) -> Text:
    """Return the proc state colored by the shared severity vocabulary."""
    from sase.ace.tui._service_severity import proc_clean_exit, service_proc_style

    style = service_proc_style(
        proc.state,
        proc.desired,
        available=getattr(proc, "available", True),
        enabled=getattr(getattr(proc, "enablement", None), "enabled", True),
        clean_exit=proc_clean_exit(proc),
    )
    return Text(proc.state, style=style)


def _proc_state_line(proc: Any) -> Text:
    """Return the ``state:`` line for ``proc show`` with shared coloring."""
    line = Text("  state: ")
    line.append_text(_proc_state_text(proc))
    return line


def _last_exit_cell(proc: Any) -> str:
    """Return the compact last-exit cell for the proc tables (``—`` when none)."""
    last_exit = getattr(proc, "last_exit", None)
    if last_exit is None:
        return "—"
    if getattr(last_exit, "spawn_error", None):
        return "spawn error"
    if getattr(last_exit, "signal", None) is not None:
        return f"signal {last_exit.signal}"
    if getattr(last_exit, "exit_code", None) is not None:
        return f"exit {last_exit.exit_code}"
    return "—"


def _format_last_exit(proc: Any) -> str | None:
    """Return the verbose last-exit line for ``proc show`` (None when none)."""
    last_exit = getattr(proc, "last_exit", None)
    if last_exit is None:
        return None
    parts: list[str] = []
    if getattr(last_exit, "spawn_error", None):
        parts.append(str(last_exit.spawn_error))
    elif getattr(last_exit, "signal", None) is not None:
        parts.append(f"signal {last_exit.signal}")
    elif getattr(last_exit, "exit_code", None) is not None:
        parts.append(f"exit {last_exit.exit_code}")
    else:
        return None
    if getattr(last_exit, "finished_at", None) is not None:
        parts.append(f"at {_format_epoch(last_exit.finished_at)}")
    return " ".join(parts)


def _format_epoch(value: float) -> str:
    from sase.core.time import format_local

    return format_local(value, default=str(value))


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if total >= size:
            return f"{total // size}{unit}"
    return f"{total}s"


def _restart_reason_text(proc: Any) -> str | None:
    restart = getattr(proc, "restart", None)
    reason: Any = None
    if isinstance(restart, dict):
        reason = restart.get("reason")
    elif restart is not None:
        reason = getattr(restart, "reason", None)
    return str(reason) if reason else None


def _stop_provenance_text(proc: Any) -> str | None:
    stop = getattr(proc, "stop", None)
    if stop is None:
        return None
    if isinstance(stop, dict):
        by, reason = stop.get("stopped_by"), stop.get("reason")
    else:
        by, reason = getattr(stop, "stopped_by", None), getattr(stop, "reason", None)
    if by and reason:
        return f"{by} ({reason})"
    if by or reason:
        return str(by or reason)
    return None


def _pending_request_text(proc: Any) -> str | None:
    request = getattr(proc, "request", None)
    if request is None:
        return None
    if isinstance(request, dict):
        action = request.get("action", "?")
        generation = request.get("generation", "?")
        completed = request.get("completed_generation")
    else:
        action = getattr(request, "action", "?")
        generation = getattr(request, "generation", "?")
        completed = getattr(request, "completed_generation", None)
    try:
        pending = completed is None or int(completed) < int(generation)
    except (TypeError, ValueError):
        pending = True
    if not pending:
        return None
    return f"{action} #{generation} pending"


def _handle_proc_enablement(args: argparse.Namespace, *, enabled: bool) -> int:
    name = str(args.name)
    action = enable_service_proc if enabled else disable_service_proc
    outcome = action(name, actor="cli")
    print(outcome.message)
    return 0 if outcome.changed else 0


def handle_service_proc_start(args: argparse.Namespace) -> int:
    name = str(args.name)
    entry = _proc_config_entry(name, command="start")
    old_pid = _proc_current_pid(name)
    outcome = start_service_proc(name, actor="cli")
    return _confirm_proc_request(args, entry, name, old_pid, outcome)


def _handle_proc_stop(args: argparse.Namespace) -> int:
    name = str(args.name)
    outcome = stop_service_proc(name, actor="cli", reason="cli")
    print(outcome.message)
    return 0


def handle_service_proc_restart(args: argparse.Namespace) -> int:
    name = str(args.name)
    entry = _proc_config_entry(name, command="restart")
    old_pid = _proc_current_pid(name)
    outcome = restart_service_proc(name, actor="cli", reason="restart")
    return _confirm_proc_request(args, entry, name, old_pid, outcome)


def _proc_config_entry(name: str, *, command: str = "") -> Any:
    del command
    return load_service_config().get(name)


def _proc_current_pid(name: str) -> int | None:
    try:
        snapshot = current_service_status()
    except Exception:  # noqa: BLE001 - a stale snapshot must not fail the request.
        return None
    row = next((proc for proc in snapshot.procs if proc.name == name), None)
    return row.pid if row is not None else None


def _confirm_proc_request(
    args: argparse.Namespace,
    entry: Any,
    name: str,
    old_pid: int | None,
    outcome: ServiceProcActionOutcome,
) -> int:
    if outcome.generation is None:
        print(outcome.message)
        return 0
    if bool(getattr(args, "no_wait", False)):
        print(outcome.message)
        if not outcome.nudged:
            print(
                f"warning: the service host is not running; generation "
                f"{outcome.generation} will be honored when it starts",
                file=sys.stderr,
            )
        return 0
    if not outcome.nudged:
        print(
            f"sase service proc {outcome.action}: the service host is not running; "
            f"generation {outcome.generation} was recorded but cannot be confirmed",
            file=sys.stderr,
        )
        return 1
    timeout = getattr(args, "timeout", None)
    if timeout is None:
        stop_timeout = entry.stop_timeout_seconds if entry is not None else 5.0
        timeout = max(15.0, stop_timeout + 10.0)
    completed = wait_for_service_proc_request(
        name, outcome.generation, timeout=float(timeout)
    )
    if completed is None:
        print(
            f"requested; the service host did not confirm within {_format_timeout(timeout)}",
            file=sys.stderr,
        )
        return 1
    return _report_proc_confirmation(outcome.action, name, old_pid, completed)


def _report_proc_confirmation(
    action: str, name: str, old_pid: int | None, completed: Any
) -> int:
    result = completed.outcome
    if result in ("restarted", "started", "already_running"):
        print(_confirmation_message(action, name, old_pid, completed))
        return 0
    detail = completed.error or f"the service host reported {result!r}"
    print(f"sase service proc {action} {name}: {detail}", file=sys.stderr)
    return 1


def _confirmation_message(
    action: str, name: str, old_pid: int | None, completed: Any
) -> str:
    if completed.outcome == "already_running":
        return f"already running: pid {completed.pid}"
    if action == "restart" and old_pid is not None:
        return f"service proc {name} restarted: pid {old_pid} -> pid {completed.pid}"
    if action == "restart":
        return f"service proc {name} restarted: pid {completed.pid}"
    return f"service proc {name} started: pid {completed.pid}"


def _format_timeout(timeout: float) -> str:
    return f"{timeout:g}s"


def _handle_proc_logs(args: argparse.Namespace) -> int:
    name = str(args.name)
    text = latest_service_log_lines(
        service_proc_output_log_path(name),
        lines=int(getattr(args, "lines", 200)),
    )
    if text:
        print(text)
    return 0


def _handle_proc_run(args: argparse.Namespace) -> int:
    command = _run_command(args)
    if not command:
        print(
            "sase service proc run: no command given; pass it after --",
            file=sys.stderr,
        )
        return 2
    cwd = Path(getattr(args, "cwd", None) or Path.cwd()).expanduser()
    label = getattr(args, "label", None) or " ".join(command)
    try:
        proc = submit_oneshot(
            command,
            label=label,
            cwd=cwd,
            project=getattr(args, "project", None),
            workspace_num=getattr(args, "workspace", None),
        )
    except ProcSubmitError as exc:
        print(f"sase service proc run: {exc}", file=sys.stderr)
        return 1
    if bool(getattr(args, "json", False)):
        json.dump(proc.to_dict(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(proc.proc_id)
    return 0


def _print_action(result: Any, args: argparse.Namespace) -> int:
    if bool(getattr(args, "json", False)):
        json.dump(
            {
                "ok": bool(result.ok),
                "changed": bool(result.changed),
                "message": str(result.message),
                "pid": result.pid,
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    else:
        print(result.message)
    return 0 if result.ok else 1


def _run_command(args: argparse.Namespace) -> list[str]:
    command = [str(part) for part in getattr(args, "proc_command", []) or []]
    if command and command[0] == "--":
        command = command[1:]
    return command


__all__ = [
    "handle_service_command",
    "handle_service_proc_restart",
    "handle_service_proc_show",
    "handle_service_proc_start",
]
