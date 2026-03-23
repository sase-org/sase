"""CLI command handlers for ``sase axe`` subcommands.

These handlers are called from ``sase.main.entry`` when the user
invokes nested axe subcommands like ``sase axe chop list``.
"""

import argparse
import sys

from sase.ace.hooks.processes import is_process_running

from .chop_script_context import (
    ChopScriptContext,
    serialize_changespecs,
    write_chop_context,
)
from .chop_script_runner import discover_chop_script, run_chop_script
from .config import AxeConfig, ChopConfig, load_axe_config
from .state import (
    ensure_lumberjack_dirs,
    read_lumberjack_status,
)


def handle_axe_chop_list(args: argparse.Namespace) -> None:
    """Print all available chops with their descriptions."""
    from rich.console import Console

    console = Console()
    config = load_axe_config()
    seen: dict[str, ChopConfig] = {}
    for lumberjack in config.lumberjacks.values():
        for chop in lumberjack.chops:
            if chop.name not in seen:
                seen[chop.name] = chop
    for chop in sorted(seen.values(), key=lambda c: c.name):
        label = f"[bold cyan]{chop.name}[/bold cyan]"
        if chop.agent is not None:
            label += f"  [magenta](agent: {chop.agent})[/magenta]"
        console.print(label)
        if chop.description:
            console.print(f"  [dim]{chop.description}[/dim]")
    sys.exit(0)


def handle_axe_chop_run(args: argparse.Namespace) -> None:
    """Run a single chop once in the foreground, then exit."""
    chop_name: str = args.chop_name
    config = load_axe_config()

    # Check if this is an agent chop (defined in config with agent field)
    chop_config = _find_chop_config(chop_name, config)
    if chop_config is not None and chop_config.agent is not None:
        _run_agent_chop_oneshot(chop_config)
        return

    # Script-based chop
    script = discover_chop_script(chop_name, config.chop_script_dirs)
    if script is None:
        print(f"Error: unknown chop '{chop_name}'")
        sys.exit(1)

    from sase.ace.changespec import find_all_changespecs
    from sase.ace.query import evaluate_query, parse_query

    query: str = getattr(args, "query", "") or config.query

    max_hook_runners: int = (
        getattr(args, "max_hook_runners", None) or config.max_hook_runners
    )
    max_agent_runners: int = (
        getattr(args, "max_agent_runners", None) or config.max_agent_runners
    )
    zombie_timeout: int = (
        getattr(args, "zombie_timeout", None) or config.zombie_timeout_seconds
    )

    all_changespecs = find_all_changespecs()
    filtered_changespecs = all_changespecs
    if query:
        parsed = parse_query(query)
        filtered_changespecs = [
            cs for cs in all_changespecs if evaluate_query(parsed, cs, all_changespecs)
        ]

    state_dir = ensure_lumberjack_dirs("_oneshot")
    tick_dir = state_dir / "tick"
    tick_dir.mkdir(parents=True, exist_ok=True)

    all_cs_file = str(tick_dir / "all_changespecs.json")
    filtered_cs_file = str(tick_dir / "filtered_changespecs.json")
    context_file = str(tick_dir / "context.json")

    serialize_changespecs(all_changespecs, all_cs_file)
    serialize_changespecs(filtered_changespecs, filtered_cs_file)

    ctx = ChopScriptContext(
        max_hook_runners=max_hook_runners,
        max_agent_runners=max_agent_runners,
        zombie_timeout_seconds=zombie_timeout,
        query=query,
        lumberjack_name="_oneshot",
        state_dir=str(state_dir),
        all_changespecs_file=all_cs_file,
        filtered_changespecs_file=filtered_cs_file,
    )
    write_chop_context(ctx, context_file)

    chop_env = chop_config.env if chop_config is not None else {}
    result = run_chop_script(script, context_file, env=chop_env)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    sys.exit(result.returncode)


def _find_chop_config(chop_name: str, config: AxeConfig) -> ChopConfig | None:
    """Look up a chop by name across all lumberjack configs."""
    for lumberjack in config.lumberjacks.values():
        for chop in lumberjack.chops:
            if chop.name == chop_name:
                return chop
    return None


def _run_agent_chop_oneshot(chop: ChopConfig) -> None:
    """Run an agent chop as a one-shot launch."""
    from sase.agent.launcher import launch_agent_from_cwd

    assert chop.agent is not None
    try:
        result = launch_agent_from_cwd(chop.agent)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Agent started for chop '{chop.name}' (PID {result.pid})")
    sys.exit(0)


def handle_axe_lumberjack_list(args: argparse.Namespace) -> None:
    """Print configured lumberjack names and their chops."""
    from rich.console import Console

    console = Console()
    config = load_axe_config()
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
    config = load_axe_config()

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
