"""Handler for the 'sase axe' command."""

import argparse
import os
import sys

from sase.ace.query import QueryParseError


def handle_axe_command(args: argparse.Namespace) -> None:
    """Handle the 'sase axe' command."""
    # Wire --vcs-provider to env var for downstream resolution
    vcs_provider = getattr(args, "vcs_provider", None)
    if vcs_provider is not None:
        os.environ["SASE_VCS_PROVIDER"] = vcs_provider

    axe_sub = getattr(args, "axe_subcommand", None)

    if axe_sub == "chop":
        _handle_chop(args)
    elif axe_sub == "lumberjack":
        _handle_lumberjack(args)
    elif axe_sub == "maintenance":
        _handle_maintenance(args)
    elif axe_sub == "start":
        _handle_start(args)
    elif axe_sub == "stop":
        _handle_stop()
    else:
        print("Usage: sase axe {chop,lumberjack,maintenance,start,stop}")
        sys.exit(1)


def _handle_chop(args: argparse.Namespace) -> None:
    """Handle 'sase axe chop' subcommands."""
    from sase.axe.cli import handle_axe_chop_list, handle_axe_chop_run

    chop_sub = getattr(args, "axe_chop_subcommand", None)
    if chop_sub == "list":
        handle_axe_chop_list(args)
    elif chop_sub == "run":
        handle_axe_chop_run(args)
    else:
        print("Usage: sase axe chop {list,run}")
        sys.exit(1)


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


def _handle_start(args: argparse.Namespace) -> None:
    """Handle 'sase axe start' — orchestrator mode."""
    from sase.axe.config import AxeConfig, load_axe_config
    from sase.axe.orchestrator import Orchestrator

    config = load_axe_config()

    # Apply CLI overrides
    max_hook_runners = (
        args.max_hook_runners
        if args.max_hook_runners is not None
        else config.max_hook_runners
    )
    max_agent_runners = (
        args.max_agent_runners
        if args.max_agent_runners is not None
        else config.max_agent_runners
    )
    zombie_timeout = (
        args.zombie_timeout
        if args.zombie_timeout is not None
        else config.zombie_timeout_seconds
    )
    query = args.query or config.query

    config = AxeConfig(
        max_hook_runners=max_hook_runners,
        max_agent_runners=max_agent_runners,
        zombie_timeout_seconds=zombie_timeout,
        query=query,
        lumberjacks=config.lumberjacks,
    )

    try:
        orchestrator = Orchestrator(config)
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)
    success = orchestrator.run()
    sys.exit(0 if success else 1)


def _handle_stop() -> None:
    """Handle 'sase axe stop'."""
    import time as _time

    from rich.console import Console

    from sase.axe.process import stop_axe_daemon

    console = Console()
    t0 = _time.monotonic()
    if stop_axe_daemon():
        elapsed = _time.monotonic() - t0
        console.print(
            f"[bold green]Axe stopped[/bold green] — all lumberjacks"
            f" terminated in [cyan]{elapsed:.1f}s[/cyan]"
        )
    else:
        console.print("[bold yellow]Axe orchestrator is not running.[/bold yellow]")
    sys.exit(0)
