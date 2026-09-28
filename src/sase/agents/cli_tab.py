"""``sase agent tab`` — move agents between Agents-tab placements."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.names import find_named_agent


def _read_json(path: Path) -> dict[str, Any]:
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


def _stored_tab(meta: Mapping[str, Any]) -> str | None:
    value = meta.get("agent_tab")
    return value if isinstance(value, str) and value else None


def _session_of(meta: Mapping[str, Any]) -> str | None:
    for key in ("agent_session", "agent_family"):
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _iter_local_metas() -> Any:
    """Yield ``(artifacts_dir, meta)`` for every local ace-run artifact dir."""
    from sase.agent.names._lookup_artifacts import iter_ace_run_artifact_dirs

    for artifacts_dir in iter_ace_run_artifact_dirs():
        yield artifacts_dir, _read_json(artifacts_dir / "agent_meta.json")


def _root_member_dirs(meta: Mapping[str, Any]) -> list[Path]:
    """Return artifact dirs sharing the presentation root described by *meta*.

    Session follow-ups share ``agent_session``; clan members share the
    ``(agent_clan, agent_clan_generation)`` pair. Anything else moves alone:
    display surfaces resolve through the root, so the root's own write is
    what places the container.
    """
    session = _session_of(meta)
    clan = meta.get("agent_clan")
    generation = meta.get("agent_clan_generation")
    clan_key = (
        (clan, generation)
        if isinstance(clan, str) and clan and isinstance(generation, str)
        else None
    )
    if session is None and clan_key is None:
        return []
    members: list[Path] = []
    for artifacts_dir, other in _iter_local_metas():
        if session is not None and _session_of(other) == session:
            members.append(artifacts_dir)
        elif (
            clan_key is not None
            and (
                other.get("agent_clan"),
                other.get("agent_clan_generation"),
            )
            == clan_key
        ):
            members.append(artifacts_dir)
    return members


def handle_agents_tab(args: argparse.Namespace) -> None:
    """Dispatch ``sase agent tab {list,set,unset}``."""
    sub = getattr(args, "tab_subcommand", None) or "list"
    if sub == "set":
        _handle_tab_set(args)
        return
    if sub == "unset":
        _handle_tab_unset(args)
        return
    if sub == "list":
        _handle_tab_list(args)
        return

    print("Usage: sase agent tab {list,set,unset}", file=sys.stderr)
    sys.exit(1)


def _canonical_or_exit(raw_tab: str) -> str:
    """Canonicalize a destination tab name, exiting 2 with guidance on error."""
    from sase.core.agent_tab import canonicalize_agent_tab

    try:
        stored = canonicalize_agent_tab(raw_tab)
    except (ValueError, TypeError) as exc:
        print(f"Invalid tab: {exc}", file=sys.stderr)
        sys.exit(2)
    if stored is None:
        print(
            "Invalid tab: 'main' is the default tab — "
            "use `sase agent tab unset` to move there",
            file=sys.stderr,
        )
        sys.exit(2)
    return stored


def _resolve_or_exit(name: str) -> tuple[str, dict[str, Any]]:
    agent = find_named_agent(name)
    if agent is None:
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)
    meta = _read_json(Path(agent.artifacts_dir) / "agent_meta.json")
    return agent.artifacts_dir, meta


def _move_root(name: str, tab: str | None) -> None:
    artifacts_dir, meta = _resolve_or_exit(name)
    if tab is not None:
        tab = _canonical_or_exit(tab)
    current = _stored_tab(meta)
    if current == tab:
        where = tab if tab is not None else "the default tab"
        print(f"{name} is already on {where}")
        return

    from sase.ops.commands._agent_directive import persist_directive_from_payload

    targets = [Path(artifacts_dir), *_root_member_dirs(meta)]
    seen: set[str] = set()
    moved = 0
    for target in targets:
        key = str(target)
        if key in seen:
            continue
        seen.add(key)
        payload: dict[str, Any] = {"artifacts_dir": key}
        payload["prompt"] = {"kind": "set_tab", "tab": tab}
        if tab is not None:
            payload["meta_set"] = {
                "agent_tab": tab,
                "agent_tab_source": "moved",
            }
        else:
            payload["meta_remove"] = ["agent_tab", "agent_tab_source"]
        persist_directive_from_payload(payload, artifacts_dir=key)
        moved += 1

    extra = f" ({moved} agents in root)" if moved > 1 else ""
    if tab is not None:
        print(f"Moved {name}{extra} to tab '{tab}'")
    else:
        print(f"Moved {name}{extra} to the default tab")


def _handle_tab_set(args: argparse.Namespace) -> None:
    name: str = args.name
    raw_tab: str | None = args.tab
    if not raw_tab:
        print("--tab is required", file=sys.stderr)
        sys.exit(2)
    _move_root(name, raw_tab)


def _handle_tab_unset(args: argparse.Namespace) -> None:
    _move_root(args.name, None)


def _handle_tab_list(args: argparse.Namespace) -> None:
    from sase.core.agent_tab import build_agent_tab_catalog

    name: str | None = getattr(args, "name", None)
    as_json: bool = bool(getattr(args, "json", False))

    roots: list[dict[str, Any]] = []
    name_tab: str | None = None
    for _artifacts_dir, meta in _iter_local_metas():
        tab = _stored_tab(meta)
        roots.append({"agent_tab": tab, "owner": {"kind": "local"}})
        if name is not None and meta.get("name") == name:
            name_tab = tab

    if (
        name is not None
        and name_tab is None
        and not any(meta.get("name") == name for _, meta in _iter_local_metas())
    ):
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)

    catalog = build_agent_tab_catalog(
        roots,
        machine_mode=False,
        machine_order=[],
        named_order={},
    )
    entries = [
        entry
        for entry in catalog.entries
        if name is None
        or (entry.key.kind == "named" and entry.key.value == name_tab)
        or (entry.key.kind == "default" and name_tab is None)
    ]
    if as_json:
        json.dump(
            [
                {
                    "key": entry.key.kind
                    if entry.key.kind == "default"
                    else f"{entry.key.kind}:{entry.key.value}",
                    "label": entry.label,
                    "root_count": entry.root_count,
                }
                for entry in entries
            ],
            sys.stdout,
        )
        sys.stdout.write("\n")
        return

    if not entries:
        print("No agent tabs yet — launch with %tab:<name> to create one.")
        return
    try:
        from rich.console import Console
        from rich.table import Table

        table = Table(title="Agent tabs", show_header=True)
        table.add_column("Tab")
        table.add_column("Roots", justify="right")
        for entry in entries:
            label = entry.label or (
                entry.key.value if entry.key.kind == "named" else "main"
            )
            table.add_row(label, str(entry.root_count))
        Console().print(table)
    except Exception:  # noqa: BLE001 - rich is decorative; fall back to plain.
        for entry in entries:
            label = entry.label or (
                entry.key.value if entry.key.kind == "named" else "main"
            )
            print(f"{label}: {entry.root_count}")
