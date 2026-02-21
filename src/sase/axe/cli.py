"""CLI command handlers for ``sase axe`` subcommands.

These handlers are called from ``sase.main.entry`` when the user
invokes nested axe subcommands like ``sase axe chop list``.
"""

import argparse
import sys

from sase.ace.hooks.processes import is_process_running

from .chop_registry import ChopContext, get_chop, list_chops
from .config import AxeConfig, LumberjackConfig, load_axe_config
from .state import (
    AxeMetrics,
    ensure_lumberjack_dirs,
    read_lumberjack_status,
)


def handle_axe_chop_list(args: argparse.Namespace) -> None:
    """Print all registered chop names."""
    for name in list_chops():
        print(name)
    sys.exit(0)


def handle_axe_chop_run(args: argparse.Namespace) -> None:
    """Run a single chop once in the foreground, then exit."""
    from sase.ace.changespec import find_all_changespecs
    from sase.ace.query import QueryExpr, parse_query

    from .runner_pool import RunnerPool

    chop_name: str = args.chop_name
    try:
        chop_func = get_chop(chop_name)
    except KeyError:
        print(f"Error: unknown chop '{chop_name}'")
        sys.exit(1)

    config = load_axe_config()
    parsed_query: QueryExpr | None = None
    query: str = getattr(args, "query", "") or config.query
    if query:
        parsed_query = parse_query(query)

    max_runners: int = getattr(args, "max_runners", None) or config.max_runners
    zombie_timeout: int = (
        getattr(args, "zombie_timeout", None) or config.zombie_timeout_seconds
    )

    all_changespecs = find_all_changespecs()
    filtered_changespecs = all_changespecs
    if parsed_query:
        from sase.ace.query import evaluate_query

        filtered_changespecs = [
            cs
            for cs in all_changespecs
            if evaluate_query(parsed_query, cs, all_changespecs)
        ]

    state_dir = ensure_lumberjack_dirs("_oneshot")

    def _log(message: str, style: str | None = None) -> None:
        print(message)

    ctx = ChopContext(
        log_callback=_log,
        runner_pool=RunnerPool(max_runners),
        metrics=AxeMetrics(),
        parsed_query=parsed_query,
        max_runners=max_runners,
        zombie_timeout_seconds=zombie_timeout,
        all_changespecs=all_changespecs,
        filtered_changespecs=filtered_changespecs,
        lumberjack_name="_oneshot",
        state_dir=state_dir,
    )

    chop_func(ctx)
    sys.exit(0)


def handle_axe_lumberjack_list(args: argparse.Namespace) -> None:
    """Print configured lumberjack names and their chops."""
    config = load_axe_config()
    for name, lj in sorted(config.lumberjacks.items()):
        chops_str = ", ".join(lj.chops)
        print(f"{name}  (interval={lj.interval}s, chops=[{chops_str}])")
    sys.exit(0)


def handle_axe_lumberjack_run(args: argparse.Namespace) -> None:
    """Run a single lumberjack in the foreground."""
    from sase.ace.query import QueryParseError

    from .lumberjack import Lumberjack

    lj_name: str = args.lumberjack_name
    config = load_axe_config()

    # Apply CLI overrides to AxeConfig
    query = getattr(args, "query", "") or config.query
    max_runners = getattr(args, "max_runners", None) or config.max_runners
    zombie_timeout = (
        getattr(args, "zombie_timeout", None) or config.zombie_timeout_seconds
    )

    config = AxeConfig(
        max_runners=max_runners,
        zombie_timeout_seconds=zombie_timeout,
        query=query,
        lumberjacks=config.lumberjacks,
    )

    if lj_name not in config.lumberjacks:
        print(f"Error: unknown lumberjack '{lj_name}'")
        print(f"Available: {', '.join(sorted(config.lumberjacks))}")
        sys.exit(1)

    lj_config = config.lumberjacks[lj_name]

    try:
        lumberjack = Lumberjack(lj_name, lj_config, config)
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)

    success = lumberjack.run()
    sys.exit(0 if success else 1)


def handle_axe_lumberjack_status(args: argparse.Namespace) -> None:
    """Show status of all lumberjacks."""
    config = load_axe_config()
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
