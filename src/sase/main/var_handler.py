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
        variables = parse_output_variable_assignments(args.assignments)
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


def _current_agent_name(artifacts_dir: str) -> str | None:
    env_name = os.environ.get("SASE_AGENT_NAME")
    if env_name:
        return env_name
    meta = read_json_object(Path(artifacts_dir).expanduser() / "agent_meta.json")
    name = meta.get("name")
    return name if isinstance(name, str) and name else None
