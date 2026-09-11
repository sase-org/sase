"""Handler for the 'sase axe' command."""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING

from sase.ace.query import QueryParseError
from sase.axe.process import restart_axe_daemon_result
from sase.main.update_types import RestartAxeFn

if TYPE_CHECKING:
    from sase.axe.config import AxeConfig


def handle_axe_command(args: argparse.Namespace) -> None:
    """Handle the 'sase axe' command."""
    from sase.feature_flags import install_process_feature_flags

    install_process_feature_flags()

    # Wire --vcs-provider to env var for downstream resolution
    vcs_provider = getattr(args, "vcs_provider", None)
    if vcs_provider is not None:
        os.environ["SASE_VCS_PROVIDER"] = vcs_provider

    axe_sub = getattr(args, "axe_subcommand", None)

    if axe_sub == "bgcmd-launch":
        _handle_bgcmd_launch(args)
    elif axe_sub == "chop":
        _handle_chop(args)
    elif axe_sub == "ensure":
        _handle_ensure(args)
    elif axe_sub == "lumberjack":
        _handle_lumberjack(args)
    elif axe_sub == "maintenance":
        _handle_maintenance(args)
    elif axe_sub == "restart":
        _handle_restart(args)
    elif axe_sub == "start":
        _handle_start(args)
    elif axe_sub == "status":
        _handle_status(args)
    elif axe_sub == "stop":
        _handle_stop(args)
    else:
        print(
            "Usage: sase axe "
            "{chop,ensure,lumberjack,maintenance,restart,start,status,stop}"
        )
        sys.exit(1)


def _handle_bgcmd_launch(args: argparse.Namespace) -> None:
    """Handle the internal durable ``sase axe bgcmd-launch`` command."""
    from sase.axe.bgcmd_operations import run_bgcmd_launch
    from sase.ops.cli import load_request
    from sase.ops.commands.common import run_and_finish
    from sase.ops.names import AXE_BGCMD

    def _body() -> tuple[bool, str, dict[str, object]]:
        request = load_request(AXE_BGCMD, args, required=True)
        command = request.payload.get("command")
        workspace_dir = request.payload.get("workspace_dir")
        cl_name = request.payload.get("cl_name")
        if not isinstance(command, str) or not command:
            return False, "bgcmd request payload must include command", {}
        if not isinstance(workspace_dir, str) or not workspace_dir:
            return False, "bgcmd request payload must include workspace_dir", {}
        if cl_name is not None and not isinstance(cl_name, str):
            return False, "bgcmd request payload cl_name must be a string or null", {}
        success, message, payload = run_bgcmd_launch(
            slot=int(args.slot),
            command=command,
            project=str(args.project),
            workspace_num=int(args.workspace_num),
            workspace_dir=workspace_dir,
            cl_name=cl_name,
        )
        return success, message, dict(payload)

    sys.exit(run_and_finish(operation=AXE_BGCMD, body=_body, args=args))


def _handle_chop(args: argparse.Namespace) -> None:
    """Handle 'sase axe chop' subcommands."""
    from sase.axe.cli import (
        handle_axe_chop_doctor,
        handle_axe_chop_list,
        handle_axe_chop_run,
    )

    chop_sub = getattr(args, "axe_chop_subcommand", None)
    if chop_sub == "doctor":
        handle_axe_chop_doctor(args)
    elif chop_sub == "list":
        handle_axe_chop_list(args)
    elif chop_sub == "run":
        handle_axe_chop_run(args)
    else:
        print("Usage: sase axe chop {doctor,list,run}")
        sys.exit(1)


def _handle_ensure(args: argparse.Namespace) -> None:
    """Handle ``sase axe ensure`` and its timer-management commands."""
    from rich.console import Console

    from sase.axe.ensure import (
        ensure_axe,
        install_ensure_timer,
        uninstall_ensure_timer,
    )

    console = Console()
    ensure_sub = getattr(args, "axe_ensure_subcommand", None)
    if ensure_sub == "install":
        timer_result = install_ensure_timer()
        style = "bold green" if timer_result.succeeded else "bold red"
        console.print(f"[{style}]{timer_result.message}[/{style}]")
        sys.exit(0 if timer_result.succeeded else 1)
    if ensure_sub == "uninstall":
        timer_result = uninstall_ensure_timer()
        style = "bold green" if timer_result.succeeded else "bold red"
        console.print(f"[{style}]{timer_result.message}[/{style}]")
        sys.exit(0 if timer_result.succeeded else 1)
    if ensure_sub is not None:
        print("Usage: sase axe ensure {install,uninstall}")
        sys.exit(1)

    result = ensure_axe()
    styles = {
        "failed": "bold red",
        "healed": "bold green",
        "healthy": "cyan",
        "rate_limited": "yellow",
        "stopped": "yellow",
    }
    style = styles[result.status]
    console.print(f"[{style}]{result.message}[/{style}]")
    sys.exit(0 if result.succeeded else 1)


def _handle_lumberjack(args: argparse.Namespace) -> None:
    """Handle 'sase axe lumberjack' subcommands."""
    from sase.axe.cli import (
        handle_axe_lumberjack_list,
        handle_axe_lumberjack_run,
        handle_axe_lumberjack_status,
    )

    lumberjack_sub = getattr(args, "axe_lumberjack_subcommand", None)
    if lumberjack_sub == "list":
        handle_axe_lumberjack_list(args)
    elif lumberjack_sub == "run":
        handle_axe_lumberjack_run(args)
    elif lumberjack_sub == "status":
        handle_axe_lumberjack_status(args)
    else:
        print("Usage: sase axe lumberjack {list,run,status}")
        sys.exit(1)


def _handle_maintenance(args: argparse.Namespace) -> None:
    """Handle 'sase axe maintenance' subcommands."""
    from sase.axe.maintenance import (
        clear_maintenance,
        read_maintenance,
        start_maintenance,
    )

    maintenance_sub = getattr(args, "axe_maintenance_subcommand", None)
    if maintenance_sub == "enter":
        started_marker = start_maintenance(str(args.reason))
        print(
            "Axe maintenance mode enabled "
            f"(reason: {started_marker['reason']}, pid: {started_marker['pid']})"
        )
        sys.exit(0)
    if maintenance_sub == "exit":
        if clear_maintenance():
            print("Axe maintenance mode disabled")
        else:
            print("Axe maintenance mode was not active")
        sys.exit(0)
    if maintenance_sub == "status":
        active_marker = read_maintenance()
        if active_marker is None:
            print("Axe maintenance mode is not active")
            sys.exit(1)
        print(
            "Axe maintenance mode is active "
            f"(reason: {active_marker['reason']}, "
            f"pid: {active_marker['pid']}, "
            f"started_at: {active_marker['started_at']})"
        )
        sys.exit(0)

    print("Usage: sase axe maintenance {enter,exit,status}")
    sys.exit(1)


def _handle_status(args: argparse.Namespace) -> None:
    """Handle the read-only whole-system ``sase axe status`` snapshot."""
    from sase.axe.status_collector import collect_axe_status_snapshot
    from sase.axe.status_render import (
        render_axe_status_human,
        render_axe_status_json,
    )

    snapshot = collect_axe_status_snapshot()
    if bool(getattr(args, "json", False)):
        render_axe_status_json(snapshot)
    else:
        render_axe_status_human(snapshot)
    sys.exit(snapshot.exit_code)


def _load_axe_config_with_overrides(args: argparse.Namespace) -> AxeConfig:
    """Load the effective axe config with CLI runner/query/timeout overrides applied."""
    from dataclasses import replace

    from sase.axe.config import load_axe_config

    config = load_axe_config()
    max_hook_runners = (
        args.max_hook_runners
        if getattr(args, "max_hook_runners", None) is not None
        else config.max_hook_runners
    )
    max_agent_runners = (
        args.max_agent_runners
        if getattr(args, "max_agent_runners", None) is not None
        else config.max_agent_runners
    )
    zombie_timeout = (
        args.zombie_timeout
        if getattr(args, "zombie_timeout", None) is not None
        else config.zombie_timeout_seconds
    )
    query = getattr(args, "query", "") or config.query

    return replace(
        config,
        max_hook_runners=max_hook_runners,
        max_agent_runners=max_agent_runners,
        zombie_timeout_seconds=zombie_timeout,
        query=query,
    )


def _handle_start(args: argparse.Namespace) -> None:
    """Handle 'sase axe start' — orchestrator mode."""
    from sase.axe.config import AxeConfigError
    from sase.axe.desired_state import write_desired_state
    from sase.axe.orchestrator import Orchestrator
    from sase.axe._process_start import AXE_START_SOURCE_ENV
    from sase.axe.process import (
        canonical_axe_start_command,
        should_reexec_axe_start_from_canonical,
    )

    if should_reexec_axe_start_from_canonical():
        canonical_cmd = canonical_axe_start_command()
        if canonical_cmd is not None:
            env = os.environ.copy()
            env["SASE_AXE_CANONICALIZED"] = "1"
            try:
                os.execvpe(canonical_cmd, [canonical_cmd, *sys.argv[1:]], env)
            except OSError:
                pass

    write_desired_state(
        "running",
        source=os.environ.get(AXE_START_SOURCE_ENV, "axe start"),
    )
    os.chdir(os.path.expanduser("~"))

    try:
        config = _load_axe_config_with_overrides(args)
    except AxeConfigError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    try:
        orchestrator = Orchestrator(config)
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)
    success = orchestrator.run()
    sys.exit(0 if success else 1)


def _handle_restart(
    args: argparse.Namespace,
    *,
    restart_axe_fn: RestartAxeFn = restart_axe_daemon_result,
) -> None:
    """Handle 'sase axe restart' — verified stop/start/heartbeat-verify restart."""
    import time as _time

    from rich.console import Console

    from sase.axe.config import AxeConfigError
    from sase.axe.restart_render import (
        RestartLiveRenderer,
        RestartPlainRenderer,
        render_restart_json,
        render_restart_settle_panel,
        should_render_restart_live,
    )

    as_json = bool(getattr(args, "json", False))
    verify_timeout = float(getattr(args, "verify_timeout", 15.0))

    try:
        config = _load_axe_config_with_overrides(args)
    except AxeConfigError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    if as_json:
        t0 = _time.monotonic()
        result = restart_axe_fn(config, verification_timeout=verify_timeout)
        render_restart_json(result, _time.monotonic() - t0)
        sys.exit(0 if (result.succeeded and result.verified) else 1)

    console = Console()
    t0 = _time.monotonic()
    if should_render_restart_live(as_json=as_json):
        with RestartLiveRenderer(console) as renderer:
            result = restart_axe_fn(
                config,
                verification_timeout=verify_timeout,
                on_event=renderer.handle_event,
            )
        console.print(
            render_restart_settle_panel(
                result, renderer.state, elapsed_seconds=_time.monotonic() - t0
            )
        )
    else:
        plain_renderer = RestartPlainRenderer(console)
        result = restart_axe_fn(
            config,
            verification_timeout=verify_timeout,
            on_event=plain_renderer.handle_event,
        )
    sys.exit(0 if (result.succeeded and result.verified) else 1)


def _handle_stop(args: argparse.Namespace) -> None:
    """Handle 'sase axe stop'."""
    import time as _time

    from rich.console import Console

    from sase.axe.process import stop_axe_daemon_result

    console = Console()
    t0 = _time.monotonic()
    result = stop_axe_daemon_result(force=bool(getattr(args, "force", False)))
    if result.terminated_anything:
        elapsed = _time.monotonic() - t0
        console.print(
            f"[bold green]{result.summary()}[/bold green] "
            f"in [cyan]{elapsed:.1f}s[/cyan]"
        )
    else:
        style = "bold red" if result.error else "bold yellow"
        console.print(f"[{style}]{result.summary()}[/{style}]")
    sys.exit(1 if result.error and not result.terminated_anything else 0)
