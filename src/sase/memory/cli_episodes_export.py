"""Export handler for ``sase memory episodes export``."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.core.episode_facade import episode_wire_schema_version
from sase.memory.cli_episodes_common import (
    print_json,
    project_from_args,
    validate_limit,
)
from sase.memory.episodes.export import export_episode_summaries


def handle_episode_export(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    """Handle a read-only event-readiness episode export."""

    validate_limit(args.limit, "limit")
    project = project_from_args(args)
    result = export_episode_summaries(
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
        payload = result.to_json_dict()
        payload["schema_version"] = episode_wire_schema_version()
        print_json(payload)
        return

    if not result.episodes:
        print("No episodes matched the export filters.")
        return

    for episode in result.episodes:
        importance = episode["importance"]
        time_span = episode["time_span"]
        first_event = time_span.get("first_event_at") or "undated"
        last_event = time_span.get("last_event_at") or first_event
        span = (
            first_event if first_event == last_event else f"{first_event}..{last_event}"
        )
        print(
            f"{episode['episode_id']}  {importance['band']} "
            f"({importance['score']})  {episode['status']}  {episode['title']}"
        )
        print(f"  span={span} sources={len(episode['source_refs'])}")
        factors = [str(factor["label"]) for factor in importance.get("factors", [])[:3]]
        if factors:
            print("  factors=" + "; ".join(factors))
        warnings = episode.get("safety", {}).get("warnings", [])
        if warnings:
            print("  warnings=" + "; ".join(warnings[:3]))


__all__ = [
    "handle_episode_export",
]
