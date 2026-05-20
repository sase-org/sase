"""CLI helpers for the persistent agent artifact index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rich.console import Console

from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
    replace_agent_artifact_index_dismissed_agents,
    verify_agent_artifact_index,
)
from sase.core.agent_scan_wire import agent_scan_wire_to_json_dict


def handle_agents_index(args: argparse.Namespace) -> None:
    """Dispatch ``sase agents index`` subcommands."""
    sub = getattr(args, "index_subcommand", None)
    if sub == "gc":
        _handle_agents_index_gc(args)
        return
    if sub == "rebuild":
        _handle_agents_index_rebuild(args)
        return
    if sub == "verify":
        _handle_agents_index_verify(args)
        return

    Console().print("Usage: sase agents index {gc,rebuild,verify}")
    raise SystemExit(1)


def _agent_index_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """Return ``(projects_root, index_path)`` for artifact-index commands."""
    projects_root = Path(
        getattr(args, "projects_root", None) or Path.home() / ".sase" / "projects"
    ).expanduser()
    index_path = Path(
        getattr(args, "index_path", None) or default_agent_artifact_index_path()
    ).expanduser()
    return projects_root, index_path


def _handle_agents_index_rebuild(args: argparse.Namespace) -> None:
    """Rebuild the artifact summary index from source artifacts."""
    projects_root, index_path = _agent_index_paths(args)

    update = rebuild_agent_artifact_index(index_path, projects_root)
    payload = agent_scan_wire_to_json_dict(update)
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True))
        return

    Console().print(
        f"Rebuilt agent artifact index: {update.rows_indexed} rows ({index_path})"
    )


def _handle_agents_index_verify(args: argparse.Namespace) -> None:
    """Verify the artifact summary index against source artifacts."""
    projects_root, index_path = _agent_index_paths(args)

    result = verify_agent_artifact_index(index_path, projects_root)
    payload = agent_scan_wire_to_json_dict(result)
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True))
    else:
        Console().print(json.dumps(payload, indent=2, sort_keys=True))
    raise SystemExit(0 if result.ok else 1)


def _handle_agents_index_gc(args: argparse.Namespace) -> None:
    """Repair stale artifact-index rows and dismissed identity visibility."""
    projects_root, index_path = _agent_index_paths(args)

    preflight = verify_agent_artifact_index(index_path, projects_root)
    update = rebuild_agent_artifact_index(index_path, projects_root)
    dismissed, dismissed_bundle_skipped = _load_dismissed_identities_for_gc()
    hidden_update = replace_agent_artifact_index_dismissed_agents(index_path, dismissed)

    payload = agent_scan_wire_to_json_dict(update)
    payload.update(
        {
            "corrupt_rows": preflight.corrupt_rows,
            "dismissed_rows_replaced": hidden_update.rows_deleted,
            "missing_rows_indexed": preflight.missing_rows,
            "rows_deleted": preflight.extra_rows,
            "rows_hidden": hidden_update.rows_indexed,
            "rows_skipped": update.rows_skipped + dismissed_bundle_skipped,
            "stale_rows_rewritten": preflight.stale_rows,
        }
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True))
        return

    Console().print(
        "Reconciled agent artifact index: "
        f"{payload['rows_indexed']} rows indexed, "
        f"{payload['rows_deleted']} stale rows deleted, "
        f"{payload['rows_hidden']} dismissed identities hidden, "
        f"{payload['rows_skipped']} skipped ({index_path})"
    )


def _load_dismissed_identities_for_gc() -> tuple[list[AgentCleanupIdentityWire], int]:
    """Load dismissed identities from state and bundle summaries."""
    from sase.ace.dismissed_agents import (
        load_dismissed_agents,
        load_dismissed_bundle_summaries,
        rebuild_dismissed_bundle_index,
    )

    indexed, skipped = rebuild_dismissed_bundle_index()
    del indexed
    identities = {
        AgentCleanupIdentityWire(
            agent_type=str(getattr(agent_type, "value", agent_type)),
            cl_name=str(cl_name),
            raw_suffix=None if raw_suffix is None else str(raw_suffix),
        )
        for agent_type, cl_name, raw_suffix in load_dismissed_agents()
    }

    for summary in load_dismissed_bundle_summaries(limit=None):
        identities.add(_dismissed_summary_identity(summary))

    return sorted(identities), skipped


def _dismissed_summary_identity(summary: Any) -> AgentCleanupIdentityWire:
    """Convert one dismissed bundle summary into an artifact-index identity."""
    return AgentCleanupIdentityWire(
        agent_type=str(summary.agent_type),
        cl_name=str(summary.cl_name or "unknown"),
        raw_suffix=str(summary.raw_suffix) if summary.raw_suffix else None,
    )
