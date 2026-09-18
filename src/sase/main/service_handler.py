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

from sase.procs import ProcSubmitError, ProcSubmitRequest, submit_proc_request
from sase.procs.service_meta import (
    SERVICE_PROC_MODE_ONESHOT,
    SERVICE_PROC_SOURCE_TRANSIENT,
    ProcServiceBlock,
)
from sase.service.config import ServiceConfigError, load_service_config
from sase.service.control import (
    ServiceHostDisabledError,
    current_service_status,
    latest_service_log_lines,
    nudge_service_host,
    persisted_or_current_status,
    require_service_host_enabled,
    restart_service_host,
    start_service_host,
    stop_service_host,
)
from sase.service.host import run_service_host
from sase.service.paths import service_host_log_path, service_proc_output_log_path
from sase.service.state import (
    clear_service_stop,
    record_service_stop,
    set_service_enablement,
)


def handle_service_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch top-level service commands."""
    try:
        require_service_host_enabled("sase service")
        code = _handle_service_command(args)
    except ServiceHostDisabledError as exc:
        print(str(exc), file=sys.stderr)
        code = 2
    except ServiceConfigError as exc:
        print(str(exc), file=sys.stderr)
        code = 2
    sys.exit(code)


def _handle_service_command(args: argparse.Namespace) -> int:
    subcommand = getattr(args, "service_subcommand", None) or "status"
    if subcommand == "init":
        return _phase_error("init")
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
        return _phase_error("uninstall")
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
    table = Table(title="Service procs")
    table.add_column("Name")
    table.add_column("Desired")
    table.add_column("State")
    table.add_column("Summary")
    for proc in snapshot.procs:
        table.add_row(proc.name, proc.desired, proc.state, proc.summary)
    console.print(table)
    for diagnostic in snapshot.diagnostics:
        console.print(f"[yellow]{diagnostic}[/yellow]")
    return 0 if snapshot.host.state in {"running", "starting"} else 1


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
        return _handle_proc_restart(args)
    if subcommand == "run":
        return _handle_proc_run(args)
    if subcommand == "show":
        return handle_service_proc_show(args)
    if subcommand == "start":
        return _handle_proc_start(args)
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
    table.add_column("Summary")
    for proc in snapshot.procs:
        table.add_row(
            proc.name,
            proc.enablement.summary,
            proc.desired,
            proc.state,
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
    console.print(f"  state: {proc.state}")
    if proc.launcher_summary:
        console.print(f"  launcher: {proc.launcher_summary}")
    if proc.log_path:
        console.print(f"  log: {proc.log_path}")
    if proc.unavailable_reason:
        console.print(f"  unavailable: {proc.unavailable_reason}")
    return 0


def _handle_proc_enablement(args: argparse.Namespace, *, enabled: bool) -> int:
    name = str(args.name)
    _require_configured_proc(name, command="enable" if enabled else "disable")
    outcome = set_service_enablement(name, enabled, "cli")
    nudge_service_host()
    verb = "enabled" if enabled else "disabled"
    print(f"{verb} service proc {name} for this machine")
    return 0 if outcome.changed else 0


def _handle_proc_start(args: argparse.Namespace) -> int:
    name = str(args.name)
    _require_configured_proc(name, command="start")
    clear_service_stop(name)
    nudge_service_host()
    print(f"requested service proc {name} start")
    return 0


def _handle_proc_stop(args: argparse.Namespace) -> int:
    name = str(args.name)
    _require_configured_proc(name, command="stop")
    record_service_stop(name, "cli", reason="cli")
    nudge_service_host()
    print(f"requested service proc {name} stop until next boot")
    return 0


def _handle_proc_restart(args: argparse.Namespace) -> int:
    name = str(args.name)
    _require_configured_proc(name, command="restart")
    record_service_stop(name, "cli", reason="restart")
    nudge_service_host()
    time.sleep(float(getattr(args, "delay", 0.5)))
    clear_service_stop(name)
    nudge_service_host()
    print(f"requested service proc {name} restart")
    return 0


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
        proc = submit_proc_request(
            ProcSubmitRequest(
                argv=command,
                label=label,
                cwd=cwd,
                origin="service-proc",
                project=getattr(args, "project", None),
                workspace_num=getattr(args, "workspace", None),
                service=ProcServiceBlock(
                    name=None,
                    mode=SERVICE_PROC_MODE_ONESHOT,
                    source=SERVICE_PROC_SOURCE_TRANSIENT,
                ),
            )
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


def _phase_error(command: str) -> int:
    print(
        f"sase service {command}: platform unit integration lands in sase-11y.5; "
        "use `sase service start` for the detached fallback.",
        file=sys.stderr,
    )
    return 2


def _require_configured_proc(name: str, *, command: str) -> None:
    config = load_service_config()
    if config.get(name) is None:
        print(
            f"sase service proc {command}: unknown service proc {name!r}",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _run_command(args: argparse.Namespace) -> list[str]:
    command = [str(part) for part in getattr(args, "proc_command", []) or []]
    if command and command[0] == "--":
        command = command[1:]
    return command


__all__ = ["handle_service_command", "handle_service_proc_show"]
