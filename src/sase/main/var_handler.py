"""Handler for the ``sase var`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import NoReturn

from rich.console import Console
from rich.text import Text

from sase.core.artifact_file_helpers import read_json_object
from sase.core.agent_output_variables import (
    parse_output_variable_assignments,
    read_agent_output_variables,
    set_agent_output_variables,
)
from sase.core.output_variable_display import VarLine, format_var_value_lines
from sase.core.output_variable_values import VarValue, normalize_var_value

_KEY_STYLE = "bold #87D7FF"
_VALUE_STYLES = {
    "string": "#5FD75F",
    "number": "#FFAF5F",
    "boolean": "italic #AFAFAF",
    "null": "italic #AFAFAF",
    "list": "dim",
    "map": "dim",
    "block": "dim",
}


def handle_var_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch ``sase var`` subcommands."""
    subcommand = getattr(args, "var_subcommand", None)
    if subcommand == "list":
        _handle_var_list(args)
    if subcommand == "set":
        _handle_var_set(args)

    print("Usage: sase var {list,set}", file=sys.stderr)
    sys.exit(1)


def _handle_var_list(args: argparse.Namespace) -> NoReturn:
    """Display output variables for the current SASE agent."""
    agent_artifacts_dir = _require_agent_artifacts_dir("list")
    try:
        variables = read_agent_output_variables(agent_artifacts_dir)
    except Exception as exc:
        print(f"Error: failed to list output variables: {exc}", file=sys.stderr)
        sys.exit(1)

    if bool(getattr(args, "json", False)):
        print(
            json.dumps(
                variables,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        sys.exit(0)

    if not variables:
        Console().print(Text("No output variables set.", style="dim"))
        sys.exit(0)

    lines, _ = format_var_value_lines(variables)
    console = Console()
    for line in lines:
        console.print(_styled_var_line(line))
    sys.exit(0)


def _handle_var_set(args: argparse.Namespace) -> NoReturn:
    """Persist output variables for the current SASE agent."""
    agent_artifacts_dir = _require_agent_artifacts_dir("set")

    try:
        variables = _output_variables_from_args(args)
        stored = set_agent_output_variables(agent_artifacts_dir, variables)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: failed to set output variables: {exc}", file=sys.stderr)
        sys.exit(1)

    agent_name = _current_agent_name(agent_artifacts_dir)
    if agent_name:
        print(f"agent: {agent_name}")
    print(f"keys: {', '.join(sorted(stored))}")
    print(f"artifacts_dir: {Path(agent_artifacts_dir).expanduser()}")
    sys.exit(0)


def _require_agent_artifacts_dir(subcommand: str) -> str:
    """Return this agent's artifact directory or exit with a clear error."""
    if os.environ.get("SASE_AGENT") != "1":
        print(
            f"Error: sase var {subcommand} must be run from inside a SASE agent "
            "(SASE_AGENT=1 is required)",
            file=sys.stderr,
        )
        sys.exit(1)

    agent_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not agent_artifacts_dir:
        print(
            f"Error: sase var {subcommand} requires SASE_ARTIFACTS_DIR",
            file=sys.stderr,
        )
        sys.exit(1)
    return agent_artifacts_dir


def _output_variables_from_args(args: argparse.Namespace) -> dict[str, VarValue]:
    parse_json = bool(getattr(args, "json", False))
    value = getattr(args, "value", None)
    value_file = getattr(args, "value_file", None)
    if value is None and value_file is None:
        if not parse_json:
            text_variables = parse_output_variable_assignments(args.assignments)
            variables: dict[str, VarValue] = {}
            variables.update(text_variables)
            return variables
        parsed = _split_json_assignments(args.assignments)
        return {
            key: _decode_json_value(raw_value, key=key, source="KEY=VALUE")
            for key, raw_value in parsed.items()
        }

    if len(args.assignments) != 1 or "=" in args.assignments[0]:
        raise ValueError(
            "the value-source form requires exactly one bare KEY (without '='): "
            "`sase var set KEY --value TEXT` sets exactly one variable"
        )

    key = args.assignments[0]
    if value_file is None:
        if not isinstance(value, str):
            raise ValueError("output variable --value must be a string")
        if parse_json:
            return {key: _decode_json_value(value, key=key, source="--value")}
        return {key: normalize_var_value(key, value)}
    if not isinstance(value_file, str):
        raise ValueError("output variable --value-file must be a path")

    raw_value = _read_output_variable_value(value_file)
    if parse_json:
        return {
            key: _decode_json_value(
                raw_value,
                key=key,
                source=f"--value-file {value_file}",
            )
        }
    normalized = parse_output_variable_assignments([f"{key}={raw_value}"])[key]
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return {key: normalized}


def _split_json_assignments(assignments: list[str]) -> dict[str, str]:
    """Split JSON assignments without applying the per-string-leaf cap."""
    result: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            # Reuse the established assignment error and key guidance.
            parse_output_variable_assignments([assignment])
            raise AssertionError("unreachable")
        key, raw_value = assignment.split("=", 1)
        # Validate the top-level variable name through the canonical parser,
        # while leaving the JSON document intact for its structural limits.
        parse_output_variable_assignments([f"{key}="])
        result[key] = raw_value
    return result


def _decode_json_value(raw_value: str, *, key: str, source: str) -> VarValue:
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON for output variable {key} from {source}: "
            f"{exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    return normalize_var_value(key, value)


def _styled_var_line(line: VarLine) -> Text:
    rendered = Text("  " * line.indent)
    if line.bullet:
        rendered.append("-", style="dim")
    if line.key is not None:
        if line.bullet:
            rendered.append(" ")
        rendered.append(f"{line.key}:", style=_KEY_STYLE)
        if line.text is not None:
            rendered.append(" ")
    elif line.bullet and line.text is not None:
        rendered.append(" ")
    if line.text is not None:
        rendered.append(line.text, style=_VALUE_STYLES[line.kind])
    return rendered


def _read_output_variable_value(source: str) -> str:
    if source == "-":
        try:
            return sys.stdin.read()
        except UnicodeDecodeError as exc:
            raise ValueError(
                "output variable value from stdin is not valid UTF-8"
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"could not read output variable value from stdin: {exc}"
            ) from exc

    value_path = Path(source).expanduser()
    try:
        return value_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"output variable value file not found: {value_path}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"output variable value file is not valid UTF-8: {value_path}"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"could not read output variable value file {value_path}: {exc}"
        ) from exc


def _current_agent_name(artifacts_dir: str) -> str | None:
    env_name = os.environ.get("SASE_AGENT_NAME")
    if env_name:
        return env_name
    meta = read_json_object(Path(artifacts_dir).expanduser() / "agent_meta.json")
    name = meta.get("name")
    return name if isinstance(name, str) and name else None
