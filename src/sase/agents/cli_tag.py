"""``sase agents tag`` — add, remove, and list user-managed tags on agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.agent_tags import (
    InvalidTagError,
    add_tags,
    load_agent_tags,
    remove_tags,
    save_agent_tags,
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

    Mirrors the identity scheme used by ``pinned_agents`` and
    ``dismissed_agents``.  Returns ``None`` when no agent is found.
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


def _normalize_tag_input(tag: str) -> str:
    """Strip a leading ``@`` for friendlier error messages, then validate."""
    return validate_tag_name(tag)


def handle_agents_tag(args: argparse.Namespace) -> None:
    """Dispatch ``sase agents tag {add,remove,list}``."""
    sub = getattr(args, "tag_subcommand", None)
    if sub == "add":
        _handle_tag_add(args)
        return
    if sub == "remove":
        _handle_tag_remove(args)
        return
    if sub == "list":
        _handle_tag_list(args)
        return

    print("Usage: sase agents tag {add,remove,list}", file=sys.stderr)
    sys.exit(1)


def _validate_tags_or_exit(raw_tags: list[str]) -> list[str]:
    """Validate every tag in *raw_tags* or exit(2) with a clear message."""
    cleaned: list[str] = []
    for tag in raw_tags:
        try:
            cleaned.append(_normalize_tag_input(tag))
        except InvalidTagError as exc:
            print(f"Invalid tag: {exc}", file=sys.stderr)
            sys.exit(2)
    return cleaned


def _resolve_or_exit(name: str) -> tuple[AgentType, str, str | None]:
    identity = _resolve_identity_by_name(name)
    if identity is None:
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)
    return identity


def _handle_tag_add(args: argparse.Namespace) -> None:
    name: str = args.name
    raw_tags: list[str] = list(args.tags or [])
    if not raw_tags:
        print("At least one --tag is required", file=sys.stderr)
        sys.exit(2)
    cleaned = _validate_tags_or_exit(raw_tags)
    identity = _resolve_or_exit(name)

    store = load_agent_tags()
    updated = add_tags(store, identity, cleaned)
    if not save_agent_tags(store):
        print("Failed to write agent_tags.json", file=sys.stderr)
        sys.exit(1)
    print(f"Tags for {name}: {', '.join(updated) if updated else '(none)'}")


def _handle_tag_remove(args: argparse.Namespace) -> None:
    name: str = args.name
    raw_tags: list[str] = list(args.tags or [])
    if not raw_tags:
        print("At least one --tag is required", file=sys.stderr)
        sys.exit(2)
    cleaned = _validate_tags_or_exit(raw_tags)
    identity = _resolve_or_exit(name)

    store = load_agent_tags()
    updated = remove_tags(store, identity, cleaned)
    if not save_agent_tags(store):
        print("Failed to write agent_tags.json", file=sys.stderr)
        sys.exit(1)
    print(f"Tags for {name}: {', '.join(updated) if updated else '(none)'}")


def _handle_tag_list(args: argparse.Namespace) -> None:
    name: str | None = getattr(args, "name", None)
    store = load_agent_tags()

    if name is not None:
        identity = _resolve_or_exit(name)
        tags = list(store.get(identity, ()))
        agent_type, cl_name, raw_suffix = identity
        json.dump(
            {
                "name": name,
                "agent_type": agent_type.value,
                "cl_name": cl_name,
                "raw_suffix": raw_suffix,
                "tags": tags,
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return

    out: list[dict[str, object]] = []
    for (atype, cl, suffix), tag_tuple in store.items():
        out.append(
            {
                "agent_type": atype.value,
                "cl_name": cl,
                "raw_suffix": suffix,
                "tags": list(tag_tuple),
            }
        )
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
