"""``sase agents tag`` — set, unset, and list the user-managed tag on agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.agent_tags import (
    InvalidTagError,
    load_agent_tags,
    save_agent_tags,
    set_tag,
    unset_tag,
    validate_tag_name,
)
from sase.agent.names import find_named_agent

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
        # convention for run-type agents that don't target a specific CL).
        try:
            cl_name = artifact_dir.parent.parent.parent.name
        except (AttributeError, IndexError):
            cl_name = "unknown"

    agent_type = AgentType.RUNNING
    ws_state = _read_json(artifact_dir / "workflow_state.json")
    workflow_name = ws_state.get("workflow_name")
    if isinstance(workflow_name, str) and not workflow_name.startswith("tmp_"):
        agent_type = AgentType.WORKFLOW

    return (agent_type, cl_name, raw_suffix)


def handle_agents_tag(args: argparse.Namespace) -> None:
    """Dispatch ``sase agents tag {set,unset,list}``."""
    sub = getattr(args, "tag_subcommand", None)
    if sub == "set":
        _handle_tag_set(args)
        return
    if sub == "unset":
        _handle_tag_unset(args)
        return
    if sub == "list":
        _handle_tag_list(args)
        return

    print("Usage: sase agents tag {set,unset,list}", file=sys.stderr)
    sys.exit(1)


def _validate_or_exit(raw_tag: str) -> str:
    try:
        return validate_tag_name(raw_tag)
    except InvalidTagError as exc:
        print(f"Invalid tag: {exc}", file=sys.stderr)
        sys.exit(2)


def _resolve_or_exit(name: str) -> tuple[AgentType, str, str | None]:
    identity = _resolve_identity_by_name(name)
    if identity is None:
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)
    return identity


def _handle_tag_set(args: argparse.Namespace) -> None:
    name: str = args.name
    raw_tag: str | None = args.tag
    if not raw_tag:
        print("--tag is required", file=sys.stderr)
        sys.exit(2)
    cleaned = _validate_or_exit(raw_tag)
    identity = _resolve_or_exit(name)

    store = load_agent_tags()
    set_tag(store, identity, cleaned)
    if not save_agent_tags(store):
        print("Failed to write agent_tags.json", file=sys.stderr)
        sys.exit(1)
    print(f"Tag for {name}: {cleaned}")


def _handle_tag_unset(args: argparse.Namespace) -> None:
    name: str = args.name
    identity = _resolve_or_exit(name)

    store = load_agent_tags()
    unset_tag(store, identity)
    if not save_agent_tags(store):
        print("Failed to write agent_tags.json", file=sys.stderr)
        sys.exit(1)
    print(f"Tag for {name}: (none)")


def _handle_tag_list(args: argparse.Namespace) -> None:
    name: str | None = getattr(args, "name", None)
    store = load_agent_tags()

    if name is not None:
        identity = _resolve_or_exit(name)
        tag = store.get(identity)
        agent_type, cl_name, raw_suffix = identity
        json.dump(
            {
                "name": name,
                "agent_type": agent_type.value,
                "cl_name": cl_name,
                "raw_suffix": raw_suffix,
                "tag": tag,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return

    out: list[dict[str, object]] = []
    for (atype, cl, suffix), tag in store.items():
        out.append(
            {
                "agent_type": atype.value,
                "cl_name": cl,
                "raw_suffix": suffix,
                "tag": tag,
            }
        )
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
