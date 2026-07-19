"""``sase agent tribe`` — manage user-facing agent tribes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.agent_tribes import (
    InvalidTribeError,
    load_agent_tribes,
    save_agent_tribes,
    set_tribe,
    unset_tribe,
    validate_tribe_name,
)
from sase.agent.names import find_named_agent
from sase.core.agent_artifact_paths import parse_agent_artifact_path

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import AgentType


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _resolve_identity_by_name(
    name: str,
) -> tuple[AgentType, str, str | None] | None:
    """Return the ``(AgentType, cl_name, raw_suffix)`` identity for *name*.

    Mirrors the identity scheme used by the rest of the Agents tab.
    Returns ``None`` when no agent is found.
    """
    from sase.ace.tui.models.agent import AgentType

    agent = find_named_agent(name)
    if agent is None:
        return None

    artifact_dir = Path(agent.artifacts_dir)
    raw_suffix: str | None = artifact_dir.name or None

    done = _read_json(artifact_dir / "done.json")
    cl_name_raw = done.get("cl_name")
    cl_name = cl_name_raw if isinstance(cl_name_raw, str) else None

    if cl_name is None:
        # Running agents don't get cl_name in agent_meta.json; fall back to
        # the project directory name (matches the typical ``cl_name=project``
        # convention for run-type agents that don't target a specific ChangeSpec).
        info = parse_agent_artifact_path(artifact_dir)
        cl_name = (
            info.project_name
            if info is not None
            else artifact_dir.parent.parent.parent.name or "unknown"
        )

    agent_type = AgentType.RUNNING
    ws_state = _read_json(artifact_dir / "workflow_state.json")
    workflow_name = ws_state.get("workflow_name")
    if isinstance(workflow_name, str) and not workflow_name.startswith("tmp_"):
        agent_type = AgentType.WORKFLOW

    return (agent_type, cl_name, raw_suffix)


def handle_agents_tribe(args: argparse.Namespace) -> None:
    """Dispatch ``sase agent tribe {list,set,unset}``."""
    sub = getattr(args, "tribe_subcommand", None)
    if sub == "set":
        _handle_tribe_set(args)
        return
    if sub == "unset":
        _handle_tribe_unset(args)
        return
    if sub == "list":
        _handle_tribe_list(args)
        return

    print("Usage: sase agent tribe {list,set,unset}", file=sys.stderr)
    sys.exit(1)


def _validate_or_exit(raw_tribe: str) -> str:
    try:
        return validate_tribe_name(raw_tribe)
    except InvalidTribeError as exc:
        print(f"Invalid tribe: {exc}", file=sys.stderr)
        sys.exit(2)


def _resolve_or_exit(name: str) -> tuple[AgentType, str, str | None]:
    identity = _resolve_identity_by_name(name)
    if identity is None:
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)
    return identity


def _handle_tribe_set(args: argparse.Namespace) -> None:
    name: str = args.name
    raw_tribe: str | None = args.tribe
    if not raw_tribe:
        print("--tribe is required", file=sys.stderr)
        sys.exit(2)
    cleaned = _validate_or_exit(raw_tribe)
    identity = _resolve_or_exit(name)

    store = load_agent_tribes()
    set_tribe(store, identity, cleaned)
    if not save_agent_tribes(store):
        print("Failed to write agent_tribes.json", file=sys.stderr)
        sys.exit(1)
    print(f"Tribe for {name}: @{cleaned}")


def _handle_tribe_unset(args: argparse.Namespace) -> None:
    name: str = args.name
    identity = _resolve_or_exit(name)

    store = load_agent_tribes()
    unset_tribe(store, identity)
    if not save_agent_tribes(store):
        print("Failed to write agent_tribes.json", file=sys.stderr)
        sys.exit(1)
    print(f"Tribe for {name}: (none)")


def _handle_tribe_list(args: argparse.Namespace) -> None:
    name: str | None = getattr(args, "name", None)
    store = load_agent_tribes()

    if name is not None:
        identity = _resolve_or_exit(name)
        tribe = store.get(identity)
        agent_type, cl_name, raw_suffix = identity
        json.dump(
            {
                "name": name,
                "agent_type": agent_type.value,
                "cl_name": cl_name,
                "raw_suffix": raw_suffix,
                "tribe": tribe,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return

    out: list[dict[str, object]] = []
    for (atype, cl, suffix), tribe in store.items():
        out.append(
            {
                "agent_type": atype.value,
                "cl_name": cl,
                "raw_suffix": suffix,
                "tribe": tribe,
            }
        )
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
