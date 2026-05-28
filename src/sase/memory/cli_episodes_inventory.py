"""Inventory handler for ``sase memory episodes list``."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.core.episode_facade import episode_wire_schema_version
from sase.core.episode_wire import (
    EpisodeStorageIndexRowWire,
    episode_wire_to_json_dict,
)
from sase.memory.cli_episodes_common import (
    print_json,
    project_from_args,
    validate_limit,
)
from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.index import project_episodes_dir
from sase.memory.episodes.inventory import (
    EpisodeInventoryItem,
    group_inventory_items,
    query_episode_inventory,
)


def handle_episode_list(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    validate_limit(args.limit, "limit")
    project = project_from_args(args)
    items = query_episode_inventory(
        project,
        projects_root=projects_root,
        since=args.since,
        until=args.until,
        band=args.band,
        agent=args.agent,
        changespec=args.changespec,
        bead=args.bead,
        query=args.query,
        order=args.order,
        limit=args.limit,
    )

    if getattr(args, "json", False):
        groups = [
            {
                "key": key,
                "episode_ids": [item.row.episode_id for item in group_items],
            }
            for key, group_items in group_inventory_items(items, args.group)
        ]
        print_json(
            {
                "aliases": [
                    episode_wire_to_json_dict(alias)
                    for item in items
                    for alias in item.aliases
                ],
                "episodes": [item.to_json_dict() for item in items],
                "filters": {
                    "agent": args.agent,
                    "band": args.band,
                    "bead": args.bead,
                    "changespec": args.changespec,
                    "query": args.query,
                    "since": args.since,
                    "until": args.until,
                },
                "group": args.group,
                "groups": groups,
                "order": args.order,
                "project": project,
                "schema_version": episode_wire_schema_version(),
            }
        )
        return

    if not items:
        episodes_dir = project_episodes_dir(project, projects_root=projects_root)
        print(
            "No episodes matched under "
            f"{episodes_dir.resolve(strict=False)}. Build split inventory with "
            "`sase memory episodes build --split -s <date> -u <date>`."
        )
        return

    for group_key, group_items in group_inventory_items(items, args.group):
        if group_key is not None:
            print(f"{group_key}:")
        prefix = "  " if group_key is not None else ""
        for item in group_items:
            print(prefix + _format_inventory_row(item))


def _format_inventory_row(item: EpisodeInventoryItem) -> str:
    row = item.row
    details = [
        "agents=" + (",".join(row.root_agent_names) if row.root_agent_names else "-"),
        f"chats={row.chat_count}",
        f"sources={row.source_count}",
    ]
    if row.changespec_name:
        details.append(f"changespec={row.changespec_name}")
    if row.bead_ids:
        details.append("beads=" + ",".join(row.bead_ids))
    if item.aliases:
        details.append(
            "aliases=" + ",".join(alias.alias_episode_id for alias in item.aliases)
        )
    if item.is_legacy:
        details.append("legacy")
    if item.warnings:
        details.append(f"warnings={len(item.warnings)}")
    return (
        f"{_inventory_time_span(row)}  {row.importance_band}  {row.status}  "
        f"{row.episode_id}  {row.title}  {' '.join(details)}"
    )


def _inventory_time_span(row: EpisodeStorageIndexRowWire) -> str:
    start = _format_event_timestamp(row.first_event_at)
    end = _format_event_timestamp(row.last_event_at)
    if start and end and start != end:
        return f"{start}..{end}"
    return start or end or "undated"


def _format_event_timestamp(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    compact = compact_timestamp(timestamp)
    if len(compact) >= 12 and compact[:12].isdigit():
        return (
            f"{compact[:4]}-{compact[4:6]}-{compact[6:8]} "
            f"{compact[8:10]}:{compact[10:12]}"
        )
    if len(compact) >= 8 and compact[:8].isdigit():
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    return timestamp
