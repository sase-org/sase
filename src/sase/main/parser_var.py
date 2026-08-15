"""Argument parser definition for the ``sase var`` CLI subcommand."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from typing import NoReturn

from sase.core.agent_output_variable_history_wire import (
    DEFAULT_OUTPUT_VARIABLE_KEY_LIMIT,
    DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT,
)
from sase.core.agent_output_variable_selector_wire import (
    DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT,
    OutputVariableSelectorWire,
)
from sase.core.agent_scan_facade import parse_output_variable_selector
from sase.core.output_variable_values import VarValue, normalize_var_value
from sase.main.parser_bead_common import bead_date_arg
from sase.vcs_log.dates import DATE_HELP


@dataclass(frozen=True)
class WrappedAgentTarget:
    """One fully wrapped ``<agent_name>`` snapshot target."""

    raw: str
    agent_name: str


class _VarSetArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        if "the following arguments are required: KEY[=VALUE]" in message:
            message = (
                "at least one KEY=VALUE assignment is required; the value-source "
                "form requires exactly one bare KEY (without '='): "
                "`sase var set KEY --value TEXT` sets exactly one variable"
            )
        super().error(message)


def _parse_var_list_limit(value: str) -> tuple[int, int]:
    """Parse ``KEYS[:VALUES]`` list limits. Zero means unlimited."""
    raw = value.strip()
    if ":" not in raw:
        return (_nonnegative_limit(raw, "key"), DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT)
    keys_raw, values_raw = raw.split(":", 1)
    if not keys_raw.strip() or not values_raw.strip():
        raise argparse.ArgumentTypeError(
            "must be KEYS[:VALUES], for example 20:5, 10, or 0"
        )
    return (
        _nonnegative_limit(keys_raw, "key"),
        _nonnegative_limit(values_raw, "value"),
    )


def _parse_var_value_json(value: str) -> VarValue:
    """Parse one ``--value-json`` document and apply output-variable rules."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    try:
        return normalize_var_value("value", parsed)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parse_var_selector(value: str) -> OutputVariableSelectorWire:
    """Parse one ``sase var get`` selector through the Rust domain parser."""
    try:
        return parse_output_variable_selector(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parse_var_get_target(
    value: str,
) -> WrappedAgentTarget | OutputVariableSelectorWire:
    """Parse one ``get`` target as a wrapped agent snapshot or a selector."""
    if value.startswith("<") and value.endswith(">"):
        name = value[1:-1]
        if not name.strip():
            raise argparse.ArgumentTypeError(
                "wrapped agent name cannot be empty; quote a name such as "
                "sase var get '<build>'"
            )
        return WrappedAgentTarget(raw=value, agent_name=name)
    if value.startswith("<") or value.endswith(">"):
        raise argparse.ArgumentTypeError(
            "wrapped agent name must be exactly '<agent_name>'; quote it so "
            "the shell keeps the brackets, for example sase var get '<build>'"
        )
    return _parse_var_selector(value)


class _ValidateVarGetTargets(argparse.Action):
    """Reject mixed or repeated wrapped-agent snapshot targets at parse time."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del option_string
        targets = list(values) if isinstance(values, list) else [values]
        wrapped = [
            target for target in targets if isinstance(target, WrappedAgentTarget)
        ]
        selectors = [
            target
            for target in targets
            if isinstance(target, OutputVariableSelectorWire)
        ]
        if wrapped and selectors:
            parser.error(
                "cannot mix a wrapped <agent_name> with selectors; "
                "use sase var get '<build>' for a snapshot or a selector "
                "such as build.*"
            )
        if len(wrapped) > 1:
            parser.error(
                "only one wrapped <agent_name> is allowed; "
                "use sase var get '<build>' for a single snapshot"
            )
        setattr(namespace, self.dest, targets)


class _StoreExplicitLimit(argparse.Action):
    """Store ``--limit`` and record that the user supplied it."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        del parser, option_string
        setattr(namespace, self.dest, values)
        namespace.limit_explicit = True


def _parse_var_get_limit(value: str) -> int:
    """Parse a nonnegative wildcard-expansion limit. Zero means unlimited."""
    return _nonnegative_limit(value, "match")


def _nonnegative_limit(value: str, label: str) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{label} limit must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(
            f"{label} limit must be a non-negative integer"
        )
    return parsed


def register_var_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase var`` subcommand parser."""
    var_parser = subparsers.add_parser(
        "var",
        help="Inspect and set SASE agent output variables",
        description=(
            "Inspect historical output variables, retrieve a snapshot or "
            "selector values, or set variables on the current SASE agent "
            "run.\n\n"
            "With no subcommand, `sase var` defaults to `sase var list`."
        ),
        epilog=(
            "examples:\n"
            "  sase var\n"
            "  sase var get\n"
            "  sase var get '<build>' --format json\n"
            "  sase var list --key status --limit 10:3\n"
            "  sase var get status\n"
            "  sase var get build.status --format raw\n"
            "  sase var get '*.status' --format json\n"
            '  sase var set "summary=tests passed"\n'
            "  sase var set 'cfg={\"retries\":3}' --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    var_subparsers = var_parser.add_subparsers(
        dest="var_subcommand",
        help="Variable subcommands",
        metavar="<subcommand>",
        parser_class=_VarSetArgumentParser,
        title="subcommands",
    )

    _register_var_get_parser(var_subparsers)
    _register_var_list_parser(var_subparsers)
    _register_var_set_parser(var_subparsers)


def _register_var_get_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "get",
        help="Get a snapshot or selector values",
        description=(
            "Read one output-variable snapshot or retrieve precise values by "
            "selector.\n\n"
            "With no target, read the current agent's artifact directory "
            "directly so the newest writes are visible. This form requires "
            "SASE_ARTIFACTS_DIR.\n\n"
            "With exactly one quoted <agent_name>, show the newest "
            "exact-name historical snapshot. Quote the wrapper so the shell "
            "keeps it intact, for example `sase var get '<build>' --format "
            "json`. Project filters narrow the candidate history; --hidden "
            "includes hidden agents. Exact names are preserved, including "
            "dotted, hyphenated, and digit-leading names.\n\n"
            "With one or more ordinary selectors, use the compact selector "
            "language. Unscoped keys choose the newest matching occurrence. "
            "Exact-agent selectors choose that name's newest artifact. "
            "Global (`*.KEY`) and hood (`HOOD.*.KEY`) selectors collapse "
            "repeated runs to the newest value per agent name. JSON paths "
            'use [INDEX] or ["KEY"] after the selected value; dotted map '
            "traversal is not accepted.\n\n"
            "Snapshot mode supports --format pretty|json. Selector mode also "
            "supports raw and jsonl. --limit applies only to selector "
            "wildcard expansion."
        ),
        epilog=(
            "examples:\n"
            "  sase var get\n"
            "  sase var get --format json\n"
            "  sase var get '<build>' --format json\n"
            "  sase var get '<research.final>' --project sase --hidden\n"
            "  sase var get status\n"
            "  sase var get results[0]\n"
            "  sase var get build.status --format raw\n"
            "  sase var get 'research.foo.report[\"summary\"]'\n"
            "  sase var get 'research.*.status'\n"
            "  sase var get '*.status' --format json\n"
            "  sase var get build.* --limit 0\n\n"
            "A quoted <agent_name> is a snapshot, not a selector. "
            "`sase var get build.*` remains selector mode and is distinct "
            "from `sase var get '<build>'`.\n\n"
            "Grammar: [SCOPE.]KEY[PATH ...]\n"
            "SCOPE is an exact agent name, *, or HOOD.*; KEY is a variable "
            'name or *; PATH is [INDEX] or ["JSON map key"]. Wildcard '
            f"expansion defaults to {DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT} "
            "matches; 0 means unlimited."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(limit_explicit=False)
    parser.add_argument(
        "targets",
        nargs="*",
        default=[],
        metavar="TARGET",
        type=_parse_var_get_target,
        action=_ValidateVarGetTargets,
        help=(
            "Omit for the current snapshot, quote '<agent_name>' for a named "
            "snapshot, or pass a selector such as status, build.status, "
            "*.status, or results[0]"
        ),
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["pretty", "raw", "json", "jsonl"],
        default="pretty",
        help=(
            "Output format: pretty or json for snapshots; pretty, raw, json, "
            "or jsonl for selectors (default: pretty)"
        ),
    )
    parser.add_argument(
        "-H",
        "--hidden",
        action="store_true",
        help=(
            "Include hidden indexed agents for named snapshots and selectors "
            "(visible history is the default)"
        ),
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=_parse_var_get_limit,
        default=DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT,
        action=_StoreExplicitLimit,
        metavar="N",
        help=(
            "Maximum matches from selector wildcard expansion; 0 means "
            "unlimited "
            f"(default: {DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT}). Not valid "
            "with a snapshot"
        ),
    )
    parser.add_argument(
        "-p",
        "--project",
        action="append",
        dest="projects",
        metavar="PROJECT",
        help=(
            "Filter named snapshots and selectors by project display name or "
            "alias (repeatable)"
        ),
    )


def _register_var_list_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "list",
        help="List unique output-variable keys across agent history",
        description=(
            "List unique variable keys from indexed agent history, most "
            "recently seen first. Under each key, list distinct typed values "
            "and the agent names that contributed them. Repeated filters in "
            "one dimension are ORed; different dimensions are ANDed. Bare "
            "`sase var` defaults to this command."
        ),
        epilog=(
            "examples:\n"
            "  sase var list\n"
            "  sase var list --key 'status*' --agent 'build.*'\n"
            "  sase var list --since 1w --format json\n"
            "  sase var list --value-json '\"ok\"' --limit 0\n"
            "  sase var list --project sase --hidden --limit 20:5\n\n"
            f"DATE grammar: {DATE_HELP}.\n"
            "Limits: KEYS[:VALUES] defaults to "
            f"{DEFAULT_OUTPUT_VARIABLE_KEY_LIMIT}:{DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT}; "
            "0 means unlimited for that dimension; a single number changes "
            "only the key limit."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-a",
        "--agent",
        action="append",
        dest="agents",
        metavar="GLOB",
        help="Filter by agent-name glob; hood.* includes the hood root (repeatable)",
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["pretty", "json", "jsonl"],
        default="pretty",
        help="Output format: pretty, json, or jsonl (default: pretty)",
    )
    parser.add_argument(
        "-H",
        "--hidden",
        action="store_true",
        help="Include hidden indexed agents (visible history is the default)",
    )
    parser.add_argument(
        "-k",
        "--key",
        action="append",
        dest="keys",
        metavar="GLOB",
        help="Filter by case-sensitive variable-key glob (repeatable)",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=_parse_var_list_limit,
        default=(
            DEFAULT_OUTPUT_VARIABLE_KEY_LIMIT,
            DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT,
        ),
        metavar="KEYS[:VALUES]",
        help=(
            "Maximum keys and distinct values per key; 0 means unlimited "
            f"(default: {DEFAULT_OUTPUT_VARIABLE_KEY_LIMIT}:"
            f"{DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT})"
        ),
    )
    parser.add_argument(
        "-p",
        "--project",
        action="append",
        dest="projects",
        metavar="PROJECT",
        help="Filter by project display name or alias (repeatable)",
    )
    parser.add_argument(
        "-r",
        "--reverse",
        action="store_true",
        help="Invert the normal recent-first key and value order",
    )
    parser.add_argument(
        "-s",
        "--since",
        metavar="DATE",
        type=bead_date_arg,
        help="Only variables from agents launched at/after DATE",
    )
    parser.add_argument(
        "-u",
        "--until",
        metavar="DATE",
        type=bead_date_arg,
        help="Only variables from agents launched at/before DATE",
    )
    value_filters = parser.add_mutually_exclusive_group()
    value_filters.add_argument(
        "-v",
        "--value",
        action="append",
        dest="values",
        metavar="TEXT",
        help=(
            "Case-insensitive substring match over scalar text and canonical "
            "JSON (repeatable)"
        ),
    )
    value_filters.add_argument(
        "-V",
        "--value-json",
        action="append",
        dest="value_json",
        metavar="JSON",
        type=_parse_var_value_json,
        help="Exact typed JSON value match after output-variable normalization (repeatable)",
    )


def _register_var_set_parser(subparsers: argparse._SubParsersAction) -> None:
    set_parser = subparsers.add_parser(
        "set",
        help="Set output variables for the current SASE agent",
        description=(
            "Set one or more output variables with KEY=VALUE assignments, or set "
            "one bare KEY from --value or --value-file."
        ),
        epilog=(
            "examples:\n"
            '  sase var set "summary=tests passed"\n'
            '  sase var set \'tags=["unit","integration"]\' --json\n'
            "  sase var set cfg --json --value '{\"retries\":3}'\n"
            "  sase var set report --json --value-file report.json\n"
            "  sase var set body --value-file - <<'EOF'\n"
            "first line\n"
            "second line\n"
            "EOF\n"
            "  sase var set cfg --json --value-file - <<'JSON'\n"
            '{"hosts":["a","b"],"retries":3}\n'
            "JSON"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    set_parser.add_argument(
        "assignments",
        nargs="+",
        metavar="KEY[=VALUE]",
        help=("KEY=VALUE assignment, or one bare KEY with --value or --value-file"),
    )
    set_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Parse supplied values as JSON instead of text",
    )
    value_source = set_parser.add_mutually_exclusive_group()
    value_source.add_argument(
        "-v",
        "--value",
        metavar="TEXT",
        help="Use TEXT as the value verbatim without splitting on whitespace",
    )
    value_source.add_argument(
        "-f",
        "--value-file",
        metavar="PATH",
        help="Read the value as UTF-8 text from PATH; use - for stdin",
    )
