"""CLI helpers for the persistent agent artifact index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rich.console import Console

from sase.core.agent_artifact_index_lifecycle import (
    build_dismissed_agent_projection_inputs,
)
from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_facade import (
    agent_artifact_index_status,
    default_agent_artifact_index_path,
    query_agent_artifact_index,
    prune_hidden_terminal_agent_artifact_index_rows,
    rebuild_agent_artifact_index,
    replace_agent_artifact_index_dismissed_agents,
    vacuum_agent_artifact_index,
    verify_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    agent_scan_wire_to_json_dict,
)
from sase.core.paths import sase_projects_dir


def handle_agents_index(args: argparse.Namespace) -> None:
    """Dispatch ``sase agent index`` subcommands."""
    sub = getattr(args, "index_subcommand", None)
    if sub == "gc":
        _handle_agents_index_gc(args)
        return
    if sub == "rebuild":
        _handle_agents_index_rebuild(args)
        return
    if sub == "status":
        _handle_agents_index_status(args)
        return
    if sub == "vacuum":
        _handle_agents_index_vacuum(args)
        return
    if sub == "verify":
        _handle_agents_index_verify(args)
        return

    Console().print("Usage: sase agent index {gc,rebuild,status,vacuum,verify}")
    raise SystemExit(1)


def _agent_index_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """Return ``(projects_root, index_path)`` for artifact-index commands."""
    projects_root = Path(
        getattr(args, "projects_root", None) or sase_projects_dir()
    ).expanduser()
    index_path = Path(
        getattr(args, "index_path", None) or default_agent_artifact_index_path()
    ).expanduser()
    return projects_root, index_path


def build_agent_index_status_payload(
    *,
    projects_root: Path | str | None = None,
    index_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return lightweight visible-inbox index diagnostics without scanning sources."""
    resolved_projects_root = Path(projects_root or sase_projects_dir()).expanduser()
    resolved_index_path = Path(
        index_path or default_agent_artifact_index_path()
    ).expanduser()
    return _agent_index_status_payload(resolved_projects_root, resolved_index_path)


def _handle_agents_index_rebuild(args: argparse.Namespace) -> None:
    """Rebuild the artifact summary index from source artifacts."""
    projects_root, index_path = _agent_index_paths(args)

    update = rebuild_agent_artifact_index(index_path, projects_root)
    payload = agent_scan_wire_to_json_dict(update)
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True))
        return

    Console().print(
        f"Rebuilt agent artifact index: {update.rows_indexed} rows, "
        f"{update.hidden_terminal_rows_pruned} hidden terminal rows pruned "
        f"({index_path})"
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


def _handle_agents_index_status(args: argparse.Namespace) -> None:
    """Inspect the normal visible-inbox index path without a source scan."""
    projects_root, index_path = _agent_index_paths(args)

    payload = build_agent_index_status_payload(
        projects_root=projects_root,
        index_path=index_path,
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True))
        return

    if payload["repair_recommended"]:
        Console().print(
            "Agent artifact index repair recommended: "
            f"{payload['repair_reason']} ({index_path})"
        )
        Console().print("Run: sase agent index verify")
        Console().print("Repair: sase agent index gc")
        return

    Console().print(
        "Agent artifact index ready for normal refresh: "
        f"{payload['visible_rows']} visible rows, "
        f"{payload['dismissed_projection_rows']} dismissed identities, "
        f"{payload['hidden_terminal_rows_retained']} hidden terminal rows retained "
        f"({index_path})"
    )


def _handle_agents_index_vacuum(args: argparse.Namespace) -> None:
    """Report or reclaim freelist space in the persistent artifact index."""
    _, index_path = _agent_index_paths(args)
    apply = bool(getattr(args, "apply", False))
    as_json = bool(getattr(args, "json", False))

    if not apply:
        status = agent_artifact_index_status(index_path)
        payload: dict[str, Any] = {
            "applied": False,
            "index_path": str(index_path),
            "dismissed_agents_rows": status.dismissed_agents_rows,
            "freelist_pages": status.freelist_pages,
            "freelist_bytes": status.freelist_bytes,
            "file_size_bytes": status.file_size_bytes,
        }
        if as_json:
            print(json.dumps(payload, sort_keys=True))
            return
        console = Console()
        console.print(f"Artifact index freelist report ({index_path})")
        console.print(f"  File size          [bold]{status.file_size_bytes:,}[/bold] B")
        console.print(
            f"  Freelist pages     [bold]{status.freelist_pages:,}[/bold] "
            f"({status.freelist_bytes:,} B)"
        )
        console.print(
            f"  Dismissed rows     [bold]{status.dismissed_agents_rows:,}[/bold]"
        )
        if status.freelist_pages:
            console.print(
                "\nRun [bold]sase agent index vacuum --apply[/bold] to reclaim "
                "the freelist. VACUUM rebuilds the file losslessly; it never "
                "removes or alters a row."
            )
        return

    update = vacuum_agent_artifact_index(index_path)
    payload = {
        "applied": True,
        "index_path": update.index_path,
        "freelist_pages_before": update.freelist_pages_before,
        "freelist_pages_after": update.freelist_pages_after,
        "file_size_bytes_before": update.file_size_bytes_before,
        "file_size_bytes_after": update.file_size_bytes_after,
        "bytes_reclaimed": update.bytes_reclaimed,
    }
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    Console().print(
        "Vacuumed agent artifact index: "
        f"{update.bytes_reclaimed:,} B reclaimed, "
        f"freelist {update.freelist_pages_before:,} -> "
        f"{update.freelist_pages_after:,} pages "
        f"({index_path})"
    )


def _agent_index_status_payload(
    projects_root: Path, index_path: Path
) -> dict[str, Any]:
    """Return lightweight operator diagnostics for the visible-inbox path."""
    base: dict[str, Any] = {
        "index_path": str(index_path),
        "projects_root": str(projects_root),
        "index_exists": index_path.is_file(),
        "complete_history": False,
        "complete_visible_inbox": False,
        "alias_rows": 0,
        "dismissed_projection_rows": 0,
        "hidden_terminal_retention_limit": 0,
        "hidden_terminal_rows_prunable": 0,
        "hidden_terminal_rows_retained": 0,
        "indexed_rows": 0,
        "normal_refresh": "visible-inbox artifact-index query",
        "repair_command": "sase agent index gc",
        "repair_reason": None,
        "repair_recommended": False,
        "schema_version": 0,
        "verify_command": "sase agent index verify",
        "visible_rows": 0,
    }
    if not base["index_exists"]:
        base.update(
            {
                "repair_recommended": True,
                "repair_reason": "artifact_index_missing",
            }
        )
        return base

    try:
        status = agent_artifact_index_status(index_path)
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
        base.update(
            {
                "repair_recommended": True,
                "repair_reason": f"artifact_index_status_failed: {exc}",
            }
        )
        return base

    base["schema_version"] = status.schema_version
    base["indexed_rows"] = status.agent_artifacts_rows
    base["dismissed_projection_rows"] = status.dismissed_agents_rows
    base["alias_rows"] = status.agent_artifact_aliases_rows
    base["hidden_terminal_retention_limit"] = status.hidden_terminal_retention_limit
    base["hidden_terminal_rows_prunable"] = status.hidden_terminal_rows_prunable
    base["hidden_terminal_rows_retained"] = status.hidden_terminal_rows_retained
    try:
        snapshot = query_agent_artifact_index(
            index_path,
            projects_root,
            query=AgentArtifactIndexQueryWire(
                include_active=True,
                include_recent_completed=True,
                include_full_history=False,
                active_limit=None,
                recent_completed_limit=200,
                include_hidden=False,
            ),
        )
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
        base.update(
            {
                "repair_recommended": True,
                "repair_reason": f"artifact_index_query_failed: {exc}",
            }
        )
        return base

    soft_errors = snapshot.stats.json_decode_errors + snapshot.stats.os_errors
    base.update(
        {
            "complete_visible_inbox": soft_errors == 0,
            "repair_recommended": soft_errors > 0,
            "repair_reason": "artifact_index_query_soft_errors"
            if soft_errors
            else None,
            "visible_rows": len(snapshot.records),
        }
    )
    return base


def _handle_agents_index_gc(args: argparse.Namespace) -> None:
    """Repair stale artifact-index rows and dismissed identity visibility."""
    projects_root, index_path = _agent_index_paths(args)

    # Plain gc rebuilds the dismissed projection *from* the bundle summaries, so
    # it re-hides agents whose bundles lingered after a revive. Purging those
    # orphaned bundles first turns gc into a true repair for that case.
    revived_bundles_purged = 0
    if getattr(args, "purge_revived_bundles", False):
        revived_bundles_purged = _purge_revived_dismissed_bundles_for_gc()

    preflight = verify_agent_artifact_index(index_path, projects_root)
    update = rebuild_agent_artifact_index(index_path, projects_root)
    dismissed, dismissed_bundle_skipped = _load_dismissed_identities_for_gc()
    hidden_update = replace_agent_artifact_index_dismissed_agents(index_path, dismissed)
    prune_update = prune_hidden_terminal_agent_artifact_index_rows(index_path)

    payload = agent_scan_wire_to_json_dict(update)
    payload["hidden_terminal_rows_pruned"] += prune_update.hidden_terminal_rows_pruned
    payload["hidden_terminal_rows_retained"] = max(
        payload["hidden_terminal_rows_retained"],
        prune_update.hidden_terminal_rows_retained,
    )
    payload.update(
        {
            "corrupt_rows": preflight.corrupt_rows,
            "dismissed_rows_replaced": hidden_update.rows_deleted,
            "missing_rows_indexed": preflight.missing_rows,
            "revived_bundles_purged": revived_bundles_purged,
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
        f"{payload['hidden_terminal_rows_pruned']} hidden terminal rows pruned, "
        f"{payload['revived_bundles_purged']} revived bundles purged, "
        f"{payload['rows_skipped']} skipped ({index_path})"
    )


def _purge_revived_dismissed_bundles_for_gc() -> int:
    """Purge dismissed bundles for already-revived agents before a gc rebuild."""
    from sase.ace.dismissed_agents import purge_revived_dismissed_bundles

    return purge_revived_dismissed_bundles()


def _load_dismissed_identities_for_gc() -> tuple[list[AgentCleanupIdentityWire], int]:
    """Load dismissed identities from state and bundle summaries."""
    projection = build_dismissed_agent_projection_inputs()
    return projection.identities, projection.skipped_bundle_rows
