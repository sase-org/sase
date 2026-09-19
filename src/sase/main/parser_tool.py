"""Argument parser definition for the ``sase tool`` command group."""

from __future__ import annotations

import argparse


_RUN_STATES = (
    "created",
    "failed",
    "interrupted",
    "lost",
    "running",
    "signaled",
    "succeeded",
)


def register_tool_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase tool`` subcommand parser."""

    tool_parser = subparsers.add_parser(
        "tool",
        help="List, run, and inspect project-owned named tools",
        description=(
            "List, run, and inspect project-owned named tools and the "
            "machine-local ToolRun ledger.\n\n"
            "Bare `sase tool` defaults to `sase tool list`.\n\n"
            "Named tools are complete entries in the project's sase/sase.yml. "
            "User, machine, plugin, and builtin config cannot change argv. "
            "Ad-hoc commands require `sase tool run -- ARGV...`."
        ),
    )
    tool_subparsers = tool_parser.add_subparsers(
        dest="tool_subcommand",
        help="Tool subcommands",
        metavar="{list,run,runs,show}",
    )

    list_parser = tool_subparsers.add_parser(
        "list",
        help="List named tools with LAST and TYPICAL",
        description=(
            "Show each project-owned named tool with its newest native result "
            "(LAST) and observed median duration (TYPICAL). Missing samples "
            "render as an em dash, never as zero or an ETA."
        ),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a versioned machine-readable JSON object",
    )

    run_parser = tool_subparsers.add_parser(
        "run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Run a named tool or an ad-hoc argv",
        description=(
            "Execute a project-owned named tool, or an ad-hoc command after "
            "`--`, and record a ToolRun. Named tools run at the project root; "
            "ad-hoc commands use the invocation cwd. Extra arguments append "
            "only when the definition allows them. Tokens after `--` are "
            "preserved verbatim, including leading dashes.\n\n"
            "Humans default to exact stdout/stderr passthrough. Direct agent "
            "execution (SASE_AGENT_NAME) defaults to compact output. `-q` "
            "forces compact; `-v` forces streaming. Wrapper metadata goes to "
            "stderr. The child has no output TTY; stdin is inherited."
        ),
        epilog=(
            "examples:\n"
            "  sase tool run check\n"
            "  sase tool run test -- tests/test_tool_handler.py\n"
            "  sase tool run -- printf out\n"
            "  sase tool run -q -T 5 -- false"
        ),
    )
    output_mode = run_parser.add_mutually_exclusive_group()
    output_mode.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Force compact output (identity, result, failure tail)",
    )
    run_parser.add_argument(
        "-T",
        "--tail-lines",
        type=int,
        default=200,
        metavar="N",
        help="Retained failure lines shown in compact mode (default: 200)",
    )
    output_mode.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Force streaming passthrough of child stdout and stderr",
    )
    run_parser.add_argument(
        "tool_run_words",
        nargs=argparse.REMAINDER,
        metavar="TOOL | -- ARGV...",
        help="Named tool with optional extra args, or -- followed by argv",
    )

    runs_parser = tool_subparsers.add_parser(
        "runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="List recorded tool runs",
        description=(
            "List native ToolRuns, newest first. Defaults to the current "
            "project. Unsettled wrappers whose process is gone are marked "
            "lost before the list is rendered."
        ),
        epilog=(
            "examples:\n"
            "  sase tool runs\n"
            "  sase tool runs -t check -n 20\n"
            "  sase tool runs -s failed -j"
        ),
    )
    runs_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        dest="tool_runs_all",
        help="Include runs from every project",
    )
    runs_parser.add_argument(
        "-A",
        "--agent",
        default=None,
        metavar="AGENT",
        dest="tool_runs_agent",
        help="Filter to runs attributed to this agent",
    )
    runs_parser.add_argument(
        "-c",
        "--cursor",
        default=None,
        metavar="CURSOR",
        dest="tool_runs_cursor",
        help="Continue from a previous next_cursor value",
    )
    runs_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        dest="tool_runs_json",
        help="Emit a versioned machine-readable JSON object",
    )
    runs_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=50,
        metavar="N",
        dest="tool_runs_limit",
        help="Show at most N runs (default: 50, max: 1000)",
    )
    runs_parser.add_argument(
        "-s",
        "--state",
        choices=_RUN_STATES,
        default=None,
        metavar="STATE",
        dest="tool_runs_state",
        help="Filter to one lifecycle state",
    )
    runs_parser.add_argument(
        "-t",
        "--tool",
        default=None,
        metavar="TOOL",
        dest="tool_runs_tool",
        help="Filter to one named tool",
    )

    show_parser = tool_subparsers.add_parser(
        "show",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Show one tool run by exact id",
        description=(
            "Show one ToolRun by exact run id. `-j` emits the versioned "
            "query envelope. `-l` replays retained stdout to stdout and "
            "retained stderr to stderr without claiming a total order "
            "between streams. `-j` and `-l` cannot be combined."
        ),
        epilog=(
            "examples:\n"
            "  sase tool show 0f1a2b3c4d5e6f7a\n"
            "  sase tool show 0f1a2b3c4d5e6f7a -j\n"
            "  sase tool show 0f1a2b3c4d5e6f7a -l"
        ),
    )
    show_output = show_parser.add_mutually_exclusive_group()
    show_output.add_argument(
        "-j",
        "--json",
        action="store_true",
        dest="tool_show_json",
        help="Emit a versioned machine-readable JSON object",
    )
    show_output.add_argument(
        "-l",
        "--logs",
        action="store_true",
        dest="tool_show_logs",
        help="Replay retained stdout and stderr",
    )
    show_parser.add_argument(
        "tool_show_run_id",
        metavar="RUN",
        help="Exact tool run id",
    )


__all__ = ["register_tool_parser"]
