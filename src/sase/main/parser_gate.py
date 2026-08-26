"""Argument parser definitions for the ``sase gate`` command group."""

from __future__ import annotations

import argparse

from sase.ops.cli import add_operation_io_flags


def register_gate_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``gate`` subcommand parser."""
    gate_parser = subparsers.add_parser(
        "gate",
        help="Create or wait for durable command-backed gates",
        description=(
            "Create durable command-backed gates from versioned JSON "
            "specifications, inspect what they ask for, run their repeatable "
            "actions, answer them headlessly, and wait mechanically for their "
            "terminal results."
        ),
    )
    gate_subparsers = gate_parser.add_subparsers(
        dest="gate_subcommand",
        help="Gate subcommands",
    )

    _register_act_parser(gate_subparsers)
    _register_answer_parser(gate_subparsers)
    _register_create_parser(gate_subparsers)
    _register_show_parser(gate_subparsers)
    _register_wait_parser(gate_subparsers)


def _register_act_parser(gate_subparsers: argparse._SubParsersAction) -> None:
    """Register ``sase gate act``."""
    act_parser = gate_subparsers.add_parser(
        "act",
        help="Run one repeatable gate action without answering the gate",
        description=(
            "Run one action a gate declares. An action never answers the gate "
            "and may be run as many times as needed: a `run_command` action "
            "prints its output, and an `edit_file` action opens its edit "
            "target in $VISUAL/$EDITOR and reports whether the edit was "
            "accepted. This is the supported alternative to running a "
            "bundle's command by hand."
        ),
        epilog=(
            "exit codes:\n"
            "  0  the action ran\n"
            "  1  usage, validation, or action failure\n"
            "  3  the gate is cancelled\n\n"
            "examples:\n"
            "  sase gate act --id plan-123 --kind plan --operation edit_plan\n"
            "  sase gate act -i custom-1 -k custom -o show_diff --json\n"
            "  sase gate act -i custom-1 -k custom -o probe -I '{\"deep\": true}'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    act_parser.add_argument(
        "-i",
        "--id",
        required=True,
        metavar="REQUEST_ID",
        help="Gate request id from the creation descriptor",
    )
    act_parser.add_argument(
        "-I",
        "--input",
        default=None,
        metavar="JSON",
        help=(
            "JSON input for a run_command action, as a literal, @FILE, or - for stdin"
        ),
    )
    act_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the action result as stable machine-readable JSON",
    )
    act_parser.add_argument(
        "-k",
        "--kind",
        required=True,
        help="Gate kind from the creation descriptor",
    )
    act_parser.add_argument(
        "-o",
        "--operation",
        required=True,
        metavar="ACTION_ID",
        help="Id of the declared action to run; see `sase gate show`",
    )
    add_operation_io_flags(act_parser)


def _register_answer_parser(gate_subparsers: argparse._SubParsersAction) -> None:
    """Register ``sase gate answer``."""
    answer_parser = gate_subparsers.add_parser(
        "answer",
        help="Answer a durable gate headlessly with typed input",
        description=(
            "Answer a gate by selecting one branch's options and supplying "
            "each selected option's declared input. Input is delivered to "
            "commands as JSON on stdin and never as command arguments. "
            "Per-option values (--set, --option-input) and one shared value "
            "(--input) are mutually exclusive submission contracts."
        ),
        epilog=(
            "exit codes:\n"
            "  0  answered\n"
            "  1  usage or validation error\n"
            "  3  cancelled\n\n"
            "examples:\n"
            "  sase gate answer --id custom-1 --kind custom --option restart \\\n"
            "    --set target_env=staging --feedback 'ship it'\n"
            "  sase gate answer -i custom-1 -k custom -o restart -o verify \\\n"
            "    -O verify=@verify-input.json\n"
            "  sase gate answer -i custom-1 -k custom -o restart --resume"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    detach_group = answer_parser.add_mutually_exclusive_group()
    detach_group.add_argument(
        "-d",
        "--detach",
        action="store_true",
        help=(
            "Submit to a supervised background proc instead of answering "
            "inline, so an approved command survives this client exiting; "
            "gate shells default to this"
        ),
    )
    detach_group.add_argument(
        "-D",
        "--no-detach",
        action="store_true",
        help="Answer inline even for a gate shell, overriding its detached default",
    )
    answer_parser.add_argument(
        "-f",
        "--feedback",
        default=None,
        help=(
            "Reviewer note; delivered as input.feedback to every selected "
            "option whose schema declares it"
        ),
    )
    answer_parser.add_argument(
        "-i",
        "--id",
        required=True,
        metavar="REQUEST_ID",
        help="Gate request id from the creation descriptor",
    )
    answer_parser.add_argument(
        "-I",
        "--input",
        default=None,
        metavar="JSON",
        help=(
            "One shared JSON value for every selected option, as a literal, "
            "@FILE, or - for stdin (legacy contract)"
        ),
    )
    answer_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the stable machine-readable answered result",
    )
    answer_parser.add_argument(
        "-k",
        "--kind",
        required=True,
        help="Gate kind from the creation descriptor",
    )
    answer_parser.add_argument(
        "-o",
        "--option",
        action="append",
        default=None,
        metavar="OPTION_ID",
        help="Select one option of a single branch; repeat for an AND branch",
    )
    answer_parser.add_argument(
        "-O",
        "--option-input",
        action="append",
        default=None,
        metavar="OPTION_ID=JSON",
        help=(
            "Whole JSON input value for one selected option, as a literal, "
            "@FILE, or - for stdin; repeat per option"
        ),
    )
    retry_group = answer_parser.add_mutually_exclusive_group()
    retry_group.add_argument(
        "-R",
        "--restart",
        action="store_true",
        help="Run the whole branch again after a partially executed attempt",
    )
    retry_group.add_argument(
        "-r",
        "--resume",
        action="store_true",
        help="Continue after the failed option of a partially executed attempt",
    )
    answer_parser.add_argument(
        "-s",
        "--set",
        action="append",
        default=None,
        metavar="FIELD=VALUE",
        help=(
            "Set one declared input field, typed by its declaration, on every "
            "selected option that accepts it; repeat for more fields"
        ),
    )


def _register_create_parser(gate_subparsers: argparse._SubParsersAction) -> None:
    """Register ``sase gate create``."""
    create_parser = gate_subparsers.add_parser(
        "create",
        help="Create a durable gate from a JSON specification on stdin",
        description=(
            "Read a schema-versioned gate specification from stdin, create its "
            "verified action bundle and notification, then emit a stable JSON "
            "descriptor containing the gate kind and request id."
        ),
        epilog=(
            "examples:\n"
            "  sase gate create < gate-request.json\n"
            "  sase gate create --panel deployments --panel-icon 🚀 "
            "< gate-request.json\n"
            "  sase gate create --shell --next 'Continue after approval' "
            "< gate-request.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    create_parser.add_argument(
        "-n",
        "--next",
        default=None,
        help="Follow-up prompt for a created gate shell",
    )
    create_parser.add_argument(
        "-f",
        "--next-fork",
        default=None,
        choices=("family", "shell", "none"),
        help="Gate-shell follow-up fork policy",
    )
    create_parser.add_argument(
        "-m",
        "--next-model",
        default=None,
        help="Model selector inherited by the gate-shell follow-up",
    )
    create_parser.add_argument(
        "-N",
        "--next-output",
        action="append",
        default=None,
        choices=("none", "results", "tail", "file"),
        help="Gate-shell follow-up output channel; repeat for multiple channels",
    )
    create_parser.add_argument(
        "-o",
        "--origin-agent",
        default=None,
        help="Attribute the gate to the agent it was filed on behalf of",
    )
    create_parser.add_argument(
        "-p",
        "--panel",
        default=None,
        help="Place the gate's notification in a named notification panel tab",
    )
    create_parser.add_argument(
        "-P",
        "--panel-icon",
        default=None,
        help=(
            "Emoji or glyph identifying that panel tab; required whenever a "
            "panel is declared"
        ),
    )
    create_parser.add_argument(
        "-s",
        "--sender",
        default=None,
        help="Override the notification sender in the gate presentation",
    )
    create_parser.add_argument(
        "-G",
        "--shell",
        action="store_true",
        help="Create a gate shell that owns the decision and hands off this agent",
    )
    create_parser.add_argument(
        "-g",
        "--shell-status",
        default=None,
        help="Pending status label for the created gate shell",
    )
    create_parser.add_argument(
        "-E",
        "--shell-stop-status",
        default=None,
        help="Settled status label for the created gate shell",
    )
    create_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        help="Add a notification tag to the gate presentation; repeat to add more",
    )


def _register_show_parser(gate_subparsers: argparse._SubParsersAction) -> None:
    """Register ``sase gate show``."""
    show_parser = gate_subparsers.add_parser(
        "show",
        help="Print the branches, declared inputs, and actions of a gate",
        description=(
            "Print what a gate asks for: its branches, each option's declared "
            "input fields with their types, defaults, and choices, and every "
            "repeatable action it declares. Use it to check that a gate you "
            "authored asks for what you intended."
        ),
        epilog=(
            "exit codes:\n"
            "  0  printed\n"
            "  1  the gate could not be read\n\n"
            "examples:\n"
            "  sase gate show --id custom-1 --kind custom\n"
            "  sase gate show -i plan-123 -k plan --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    show_parser.add_argument(
        "-i",
        "--id",
        required=True,
        metavar="REQUEST_ID",
        help="Gate request id from the creation descriptor",
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the stable machine-readable gate projection",
    )
    show_parser.add_argument(
        "-k",
        "--kind",
        required=True,
        help="Gate kind from the creation descriptor",
    )


def _register_wait_parser(gate_subparsers: argparse._SubParsersAction) -> None:
    """Register ``sase gate wait``."""
    wait_parser = gate_subparsers.add_parser(
        "wait",
        help="Wait mechanically for a durable gate to reach a terminal state",
        description=(
            "Wait for a durable gate identified by the kind and request id emitted "
            "by `sase gate create`. The gate's configured timeout always applies; "
            "--timeout may impose an earlier caller deadline."
        ),
        epilog=(
            "terminal exit codes:\n"
            "  0  answered\n"
            "  3  cancelled\n"
            "  4  timeout\n\n"
            "examples:\n"
            "  sase gate wait --id custom-123 --kind custom\n"
            "  sase gate wait -i custom-123 -k custom --json\n"
            "  sase gate wait -i custom-123 -k custom --timeout 60"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    wait_parser.add_argument(
        "-i",
        "--id",
        required=True,
        metavar="REQUEST_ID",
        help="Gate request id from the creation descriptor",
    )
    wait_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the stable machine-readable terminal result",
    )
    wait_parser.add_argument(
        "-k",
        "--kind",
        required=True,
        help="Gate kind from the creation descriptor",
    )
    wait_parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Stop waiting after this many seconds, without extending the gate timeout",
    )


__all__ = ["register_gate_parser"]
