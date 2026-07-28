"""Handler for the ``sase var`` CLI subcommand."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

from sase.core.artifact_file_helpers import read_json_object
from sase.core.agent_output_variables import (
    parse_output_variable_assignments,
    set_agent_output_variables,
)


def handle_var_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch ``sase var`` subcommands."""
    subcommand = getattr(args, "var_subcommand", None)
    if subcommand == "set":
        _handle_var_set(args)

    print("Usage: sase var {set}", file=sys.stderr)
    sys.exit(1)


def _handle_var_set(args: argparse.Namespace) -> NoReturn:
    """Persist output variables for the current SASE agent."""
    if os.environ.get("SASE_AGENT") != "1":
        print(
            "Error: sase var set must be run from inside a SASE agent "
            "(SASE_AGENT=1 is required)",
            file=sys.stderr,
        )
        sys.exit(1)

    agent_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not agent_artifacts_dir:
        print(
            "Error: sase var set requires SASE_ARTIFACTS_DIR",
            file=sys.stderr,
        )
        sys.exit(1)

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


def _output_variables_from_args(args: argparse.Namespace) -> dict[str, str]:
    value = getattr(args, "value", None)
    value_file = getattr(args, "value_file", None)
    if value is None and value_file is None:
        return parse_output_variable_assignments(args.assignments)

    if len(args.assignments) != 1 or "=" in args.assignments[0]:
        raise ValueError(
            "the value-source form requires exactly one bare KEY (without '='): "
            "`sase var set KEY --value TEXT` sets exactly one variable"
        )

    key = args.assignments[0]
    if value_file is None:
        if not isinstance(value, str):
            raise ValueError("output variable --value must be a string")
        return {key: value}
    if not isinstance(value_file, str):
        raise ValueError("output variable --value-file must be a path")

    raw_value = _read_output_variable_value(value_file)
    normalized = parse_output_variable_assignments([f"{key}={raw_value}"])[key]
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return {key: normalized}


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
