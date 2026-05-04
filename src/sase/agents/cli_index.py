"""CLI helpers for the persistent agent artifact index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)
from sase.core.agent_scan_wire import agent_scan_wire_to_json_dict


def handle_agents_index(args: argparse.Namespace) -> None:
    """Dispatch ``sase agents index`` subcommands."""
    sub = getattr(args, "index_subcommand", None)
    if sub == "rebuild":
        _handle_agents_index_rebuild(args)
        return

    Console().print("Usage: sase agents index {rebuild}")
    raise SystemExit(1)


def _handle_agents_index_rebuild(args: argparse.Namespace) -> None:
    """Rebuild the artifact summary index from source artifacts."""
    projects_root = Path(
        getattr(args, "projects_root", None) or Path.home() / ".sase" / "projects"
    ).expanduser()
    index_path = Path(
        getattr(args, "index_path", None) or default_agent_artifact_index_path()
    ).expanduser()

    update = rebuild_agent_artifact_index(index_path, projects_root)
    payload = agent_scan_wire_to_json_dict(update)
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True))
        return

    Console().print(
        f"Rebuilt agent artifact index: {update.rows_indexed} rows ({index_path})"
    )
