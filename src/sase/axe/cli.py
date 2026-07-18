"""CLI command handlers for ``sase axe`` subcommands.

These handlers are called from ``sase.main.entry`` when the user
invokes nested axe subcommands like ``sase axe chop list``.
"""

import argparse
import json
import sys

from sase.ace.hooks.processes import is_process_running

from .chop_runner import (
    ONESHOT_LUMBERJACK_NAME,
    AmbiguousChopError,
    ChopNotFoundError,
    ChopRunOutcome,
    find_configured_chop,
    run_configured_chop_once,
)
from .chop_script_runner import discover_chop_script
from .config import AxeConfig, AxeConfigError, ChopConfig, load_axe_config
from .state import (
    read_chop_run_log_tail,
    read_lumberjack_status,
)


def _load_axe_config_or_exit() -> AxeConfig:
    """Load axe config and surface fail-closed diagnostics without a traceback."""
    try:
        return load_axe_config()
    except AxeConfigError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


def handle_axe_chop_list(args: argparse.Namespace) -> None:
    """List configured chops with status, plus available scripts on request."""
    from sase.axe.chop_inventory import chop_inventory_to_dict, collect_chop_inventory

    inventory = collect_chop_inventory(_load_axe_config_or_exit())

    if getattr(args, "json", False):
        payload = {
            "schema_version": 1,
            "command": "list",
            "chops": chop_inventory_to_dict(inventory),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        sys.exit(0)

    from sase.axe.chop_render import render_chop_list

    render_chop_list(
        inventory,
        available=bool(getattr(args, "available", False)),
        verbose=bool(getattr(args, "verbose", False)),
    )
    sys.exit(0)


def handle_axe_chop_doctor(args: argparse.Namespace) -> None:
    """Diagnose configured and available chop setup, exiting nonzero on ERROR."""
    from sase.axe.chop_doctor import (
        build_chop_doctor_report,
        chop_doctor_report_to_dict,
    )

    report = build_chop_doctor_report()

    if getattr(args, "json", False):
        print(json.dumps(chop_doctor_report_to_dict(report), indent=2, sort_keys=True))
    else:
        from sase.axe.chop_render import render_chop_doctor

        render_chop_doctor(report, verbose=bool(getattr(args, "verbose", False)))
    sys.exit(1 if report.status == "ERROR" else 0)


def handle_axe_chop_run(args: argparse.Namespace) -> None:
    """Run a single chop once in the foreground, then exit.

    Routes through :func:`run_configured_chop_once` so the ChangeSpecI shares context
    building, env propagation, timeout, and run-history writing with the
    scheduled lumberjack and the TUI manual-run action. When the chop name
    is not configured (a discoverable but unattached script), falls back to
    the legacy ``_oneshot`` lumberjack name so it still runs with history.

    The ``--lumberjack`` flag disambiguates chop names that appear in more
    than one configured lumberjack.
    """
    chop_name: str = args.chop_name
    lumberjack_override: str | None = getattr(args, "lumberjack", None)
    config = _load_axe_config_or_exit()

    try:
        match = find_configured_chop(config, chop_name, lumberjack_override)
        lumberjack_name = match.lumberjack_name
        chop_cfg = match.chop
        chop_timeout_default = match.lumberjack.chop_timeout
    except AmbiguousChopError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except ChopNotFoundError:
        if lumberjack_override is not None:
            print(
                f"Error: chop '{chop_name}' is not configured under lumberjack "
                f"'{lumberjack_override}'",
                file=sys.stderr,
            )
            sys.exit(1)
        # Legacy fallback: unconfigured script discoverable on disk runs under
        # the synthetic ``_oneshot`` lumberjack so history is still recorded.
        script = discover_chop_script(chop_name, config.chop_script_dirs)
        if script is None:
            print(f"Error: unknown chop '{chop_name}'", file=sys.stderr)
            sys.exit(1)
        lumberjack_name = ONESHOT_LUMBERJACK_NAME
        chop_cfg = ChopConfig(name=chop_name, description="")
        chop_timeout_default = None

    outcome = run_configured_chop_once(
        lumberjack_name=lumberjack_name,
        chop=chop_cfg,
        axe_config=config,
        chop_timeout_default=chop_timeout_default,
        source="oneshot",
        started_by="cli",
    )
    _print_outcome_and_exit(outcome)


def _print_outcome_and_exit(outcome: ChopRunOutcome) -> None:
    """Render a chop run outcome to stdout/stderr and exit with the right code."""
    if outcome.status == "success":
        _print_chop_log_tail(outcome)
        sys.exit(0)
    if outcome.status == "failure":
        _print_chop_log_tail(outcome)
        if outcome.error is not None:
            print(f"Error: {outcome.error}", file=sys.stderr)
        sys.exit(outcome.exit_code or 1)
    if outcome.status == "timeout":
        _print_chop_log_tail(outcome)
        print(f"Error: {outcome.error}", file=sys.stderr)
        sys.exit(1)
    if outcome.status == "missing_script":
        print(f"Error: {outcome.error}", file=sys.stderr)
        sys.exit(1)
    if outcome.status == "already_running":
        suffix = f" (PID {outcome.agent_pid})" if outcome.agent_pid is not None else ""
        print(
            f"Chop '{outcome.chop_name}' is already running"
            f" under lumberjack '{outcome.lumberjack_name}'{suffix}; skipping.",
            file=sys.stderr,
        )
        sys.exit(1)
    # Defensive default: unknown status surfaces with a nonzero exit code.
    print(f"Error: unexpected chop run outcome: {outcome.status}", file=sys.stderr)
    sys.exit(1)


def _print_chop_log_tail(outcome: ChopRunOutcome) -> None:
    if outcome.run_id is None:
        return
    try:
        tail = read_chop_run_log_tail(
            outcome.lumberjack_name, outcome.chop_name, outcome.run_id
        )
    except OSError:
        tail = ""
    if tail:
        sys.stdout.write(tail)
        if not tail.endswith("\n"):
            sys.stdout.write("\n")


def handle_axe_lumberjack_list(args: argparse.Namespace) -> None:
    """Print configured lumberjack names and their chops."""
    from rich.console import Console

    console = Console()
    config = _load_axe_config_or_exit()
    for i, (name, lumberjack) in enumerate(sorted(config.lumberjacks.items())):
        if i > 0:
            console.print()
        console.print(f"[bold cyan]{name}[/bold cyan]")
        console.print(f"  [dim]interval:[/dim] {lumberjack.interval}s")
        if lumberjack.chops:
            console.print("  [dim]chops:[/dim]")
            for chop in lumberjack.chops:
                console.print(f"    [green]{chop.name}[/green]")
    sys.exit(0)


def handle_axe_lumberjack_run(args: argparse.Namespace) -> None:
    """Run a single lumberjack in the foreground."""
    from sase.ace.query import QueryParseError

    from .lumberjack import Lumberjack

    lumberjack_name: str = args.lumberjack_name
    config = _load_axe_config_or_exit()

    # Apply CLI overrides to AxeConfig
    query = getattr(args, "query", "") or config.query
    max_hook_runners = (
        getattr(args, "max_hook_runners", None) or config.max_hook_runners
    )
    max_agent_runners = (
        getattr(args, "max_agent_runners", None) or config.max_agent_runners
    )
    zombie_timeout = (
        getattr(args, "zombie_timeout", None) or config.zombie_timeout_seconds
    )

    config = AxeConfig(
        max_hook_runners=max_hook_runners,
        max_agent_runners=max_agent_runners,
        zombie_timeout_seconds=zombie_timeout,
        lumberjack_log_max_bytes=config.lumberjack_log_max_bytes,
        verbose_lumberjack_diagnostics=config.verbose_lumberjack_diagnostics,
        query=query,
        chop_script_dirs=config.chop_script_dirs,
        lumberjacks=config.lumberjacks,
    )

    if lumberjack_name not in config.lumberjacks:
        print(f"Error: unknown lumberjack '{lumberjack_name}'")
        print(f"Available: {', '.join(sorted(config.lumberjacks))}")
        sys.exit(1)

    lumberjack_config = config.lumberjacks[lumberjack_name]

    try:
        lumberjack = Lumberjack(lumberjack_name, lumberjack_config, config)
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)

    success = lumberjack.run()
    sys.exit(0 if success else 1)


def handle_axe_lumberjack_status(args: argparse.Namespace) -> None:
    """Show status of all lumberjacks."""
    config = _load_axe_config_or_exit()
    any_status = False

    for name in sorted(config.lumberjacks):
        status = read_lumberjack_status(name)
        if status is None:
            print(f"{name}: not running")
            continue

        any_status = True
        running = is_process_running(status.pid)
        state = "running" if running else "stopped (stale status)"
        print(
            f"{name}: {state} "
            f"(PID {status.pid}, "
            f"cycles={status.cycles_run}, "
            f"errors={status.errors_encountered}, "
            f"uptime={status.uptime_seconds}s)"
        )

    if not any_status:
        print("No lumberjacks are currently running.")

    sys.exit(0)
