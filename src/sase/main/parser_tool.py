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
        metavar="{list,run,runs,show,stop,wait}",
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
            "preserved verbatim, including leading dashes. Options must "
            "precede TOOL or `--`.\n\n"
            "Humans default to exact stdout/stderr passthrough. Direct agent "
            "execution (SASE_AGENT_NAME) defaults to compact output. `-q` "
            "forces compact; `-v` forces streaming. Wrapper metadata goes to "
            "stderr. The child has no output TTY; stdin is inherited.\n\n"
            "`-H` hands the run off to a durable proc and returns at once "
            "with the run id. With `-H`, `-q` prints only the run id, while "
            "`-v` and `-T` are usage errors. Exit codes: 0 accepted, "
            "1 not started, 2 usage or refusal."
        ),
        epilog=(
            "examples:\n"
            "  sase tool run check\n"
            "  sase tool run test -- tests/test_tool_handler.py\n"
            "  sase tool run -- printf out\n"
            "  sase tool run -q -T 5 -- false\n"
            "  sase tool run -H check"
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
        default=None,
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
        "-H",
        "--hand-off",
        action="store_true",
        dest="hand_off",
        help="Hand the run off to a durable proc and return at once",
    )
    run_parser.add_argument(
        "tool_run_words",
        nargs=argparse.REMAINDER,
        metavar="TOOL | -- ARGV...",
        help="Named tool with optional extra args, or -- followed by argv",
    )

    adopt_parser = tool_subparsers.add_parser(
        "_adopt",
        help=argparse.SUPPRESS,
        description="Claim and run a reserved hand-off ToolRun (internal).",
    )
    adopt_parser.add_argument(
        "adopt_run_id",
        metavar="RUN",
        help=argparse.SUPPRESS,
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
            "between streams. `-F` streams the output of record until the "
            "run settles, then prints the terminal summary. `-j` and `-l` "
            "cannot be combined; `-F` and `-l` cannot be combined; "
            "`-F -j` waits, then prints the final JSON envelope. "
            "Ctrl-C detaches the viewer (exit 130); the run continues. "
            "Exit codes: 0 shown or followed, 1 store failure, "
            "2 unknown run or usage."
        ),
        epilog=(
            "examples:\n"
            "  sase tool show 0f1a2b3c4d5e6f7a\n"
            "  sase tool show 0f1a2b3c4d5e6f7a -j\n"
            "  sase tool show 0f1a2b3c4d5e6f7a -l\n"
            "  sase tool show 0f1a2b3c4d5e6f7a -F"
        ),
    )
    show_parser.add_argument(
        "-F",
        "--follow",
        action="store_true",
        dest="tool_show_follow",
        help="Stream the output of record until the run settles",
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

    stop_parser = tool_subparsers.add_parser(
        "stop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Stop one tool run by exact id",
        description=(
            "Record a durable stop request for one ToolRun, then stop it "
            "through its execution owner: a proc-owned hand-off through "
            "the proc stop path, a monitor-owned hand-off through the "
            "monitor stop path (the follow-up is suppressed), an inline "
            "run by signaling its identity-matched wrapper. A nested "
            "foreground run is refused with the owner command that stops "
            "it. Reports `stop requested` separately from `stopped`. "
            "Exit codes: 0 stop requested, stopped, or already settled; "
            "2 unknown run or refused nested run; 1 owner control failed."
        ),
        epilog=(
            "examples:\n"
            "  sase tool stop 0f1a2b3c4d5e6f7a\n"
            "  sase tool stop 0f1a2b3c4d5e6f7a -j"
        ),
    )
    stop_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        dest="tool_stop_json",
        help="Emit a versioned machine-readable JSON object",
    )
    stop_parser.add_argument(
        "tool_stop_run_id",
        metavar="RUN",
        help="Exact tool run id",
    )

    wait_parser = tool_subparsers.add_parser(
        "wait",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="Wait for one tool run to settle",
        description=(
            "Block until one ToolRun settles or the deadline passes. The "
            "run is never affected. A settled run with an exit code "
            "returns that code; a settled run without one returns 1. "
            "A passed deadline returns 124. Ctrl-C returns 130; the run "
            "continues. Exit codes: exit code of the run, 1 settled "
            "without an exit code, 124 still running, 2 unknown run or "
            "usage, 130 interrupted."
        ),
        epilog=(
            "examples:\n"
            "  sase tool wait 0f1a2b3c4d5e6f7a\n"
            "  sase tool wait 0f1a2b3c4d5e6f7a -t 90s\n"
            "  sase tool wait 0f1a2b3c4d5e6f7a -T 20"
        ),
    )
    wait_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        dest="tool_wait_json",
        help="Emit a versioned machine-readable JSON object",
    )
    wait_parser.add_argument(
        "-T",
        "--tail-lines",
        type=int,
        default=None,
        metavar="N",
        dest="tool_wait_tail_lines",
        help="Append the last N lines of the output of record",
    )
    wait_parser.add_argument(
        "-t",
        "--timeout",
        default=None,
        metavar="DURATION",
        dest="tool_wait_timeout",
        help="Deadline: bare seconds or a duration like 90s / 45m / 2h",
    )
    wait_parser.add_argument(
        "tool_wait_run_id",
        metavar="RUN",
        help="Exact tool run id",
    )


__all__ = ["register_tool_parser"]
