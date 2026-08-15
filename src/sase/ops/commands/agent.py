"""Noninteractive agent operation runners."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from sase.ops.cli import add_operation_io_flags, load_request
from sase.ops.commands.common import run_and_finish
from sase.ops.names import AGENT_PERSIST_DIRECTIVE, AGENT_REVERT


def add_agent_operation_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register focused noninteractive agent operation commands."""
    persist = subparsers.add_parser(
        "persist-directive",
        help="Persist an agent directive update from a private request sidecar",
        description=(
            "Apply one JSON-shaped agent-directive persistence spec. The "
            "artifacts directory is positional; mutation details come from "
            "the private request sidecar."
        ),
    )
    persist.add_argument(
        "artifacts_dir",
        help="Agent artifacts directory that owns the directive files",
    )
    add_operation_io_flags(persist)

    revert = subparsers.add_parser(
        "revert",
        help="Execute a previously previewed agent commit revert",
        description=(
            "Revert an agent's commits using identifiers from the command "
            "line and optional SHA/workspace details from the request sidecar."
        ),
    )
    revert.add_argument("name", help="Agent name whose commits should be reverted")
    add_operation_io_flags(revert)


def handle_agent_operation(args: argparse.Namespace) -> int:
    """Dispatch one focused agent operation command."""
    sub = getattr(args, "agent_subcommand", None)
    if sub == "persist-directive":
        return run_and_finish(
            operation=AGENT_PERSIST_DIRECTIVE,
            body=lambda: _run_persist_directive(args),
            args=args,
        )
    if sub == "revert":
        return run_and_finish(
            operation=AGENT_REVERT,
            body=lambda: _run_revert(args),
            args=args,
        )
    return 2


def _run_persist_directive(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.tui.actions.agents._directive_persistence import (
        AgentDirectivePersistenceSpec,
        AgentMetaPatch,
        AgentTribeStorePatch,
        ReadyMarkerPatch,
        persist_agent_directive_update,
        wait_meta_patch_for_token,
        waiting_marker_patch_for_token,
    )

    request = load_request(AGENT_PERSIST_DIRECTIVE, args, required=True)
    payload = dict(request.payload)
    artifacts_dir = str(payload.get("artifacts_dir") or args.artifacts_dir)
    meta_set = payload.get("meta_set")
    meta_remove = payload.get("meta_remove")
    meta_patch = None
    if isinstance(meta_set, dict) or isinstance(meta_remove, list):
        meta_patch = AgentMetaPatch(
            set_values=dict(meta_set) if isinstance(meta_set, dict) else {},
            remove_keys=tuple(str(item) for item in meta_remove)
            if isinstance(meta_remove, list)
            else (),
        )
    if payload.get("wait") and meta_patch is None:
        wait = payload["wait"] if isinstance(payload.get("wait"), dict) else {}
        meta_patch = wait_meta_patch_for_token(
            wait_names=tuple(wait.get("names") or ()),
            wait_beads=tuple(wait.get("beads") or ()),
            time_token=wait.get("time_token")
            if isinstance(wait.get("time_token"), str)
            else None,
        )
    waiting = None
    if isinstance(payload.get("waiting"), dict):
        waiting = waiting_marker_patch_for_token(
            wait_names=tuple(payload["waiting"].get("names") or ()),
            wait_beads=tuple(payload["waiting"].get("beads") or ()),
        )
    ready = None
    if isinstance(payload.get("ready"), dict):
        ready = ReadyMarkerPatch(
            resolved_deps=tuple(payload["ready"].get("resolved_deps") or ()),
            unwait=bool(payload["ready"].get("unwait", False)),
        )
    tribe = None
    if isinstance(payload.get("tribe"), dict) and payload["tribe"].get("identity"):
        identity = payload["tribe"]["identity"]
        tribe = AgentTribeStorePatch(
            identity=tuple(identity),
            tribe=payload["tribe"].get("tribe"),
        )
    result = persist_agent_directive_update(
        AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts_dir,
            meta_patch=meta_patch,
            tribe_patch=tribe,
            waiting_marker=waiting,
            ready_marker=ready,
        )
    )
    return (
        True,
        f"Persisted agent directive in {artifacts_dir}",
        {
            "artifacts_dir": artifacts_dir,
            "meta_updated": result.meta_updated,
            "ready_updated": result.ready_updated,
            "tribe_updated": result.tribe_updated,
            "waiting_updated": result.waiting_updated,
        },
    )


def _run_revert(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.revert_agent_execute import execute_agent_revert

    request = load_request(AGENT_REVERT, args)
    payload = dict(request.payload)
    workspace = payload.get("workspace_dir")
    shas = payload.get("shas")
    artifacts_dir = payload.get("artifacts_dir")
    result = execute_agent_revert(
        str(workspace) if isinstance(workspace, str) else "",
        tuple(str(item) for item in shas) if isinstance(shas, list) else None,
        agent_name=args.name,
        artifacts_dir=str(artifacts_dir) if isinstance(artifacts_dir, str) else None,
    )
    success = bool(getattr(result, "success", False))
    message = str(
        getattr(result, "message", "") or ("Reverted" if success else "Revert failed")
    )
    error = getattr(result, "error", None)
    if not success and error:
        message = str(error)
    return success, message, {"name": args.name}


__all__ = ["add_agent_operation_parsers", "handle_agent_operation"]
