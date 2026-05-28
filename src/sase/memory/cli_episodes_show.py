"""Show handler for ``sase memory episodes show``."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.core.episode_wire import EpisodeWire
from sase.memory.cli_episodes_common import (
    load_episode,
    print_file,
    print_json,
    project_from_args,
    resolve_episode_dir,
)
from sase.memory.episodes.render import (
    agent_evidence_pack_json_dict,
    render_agent_text,
    render_graph_text,
    render_lesson_markdown,
    render_overview_text,
    render_sources_text,
    render_timeline_text,
)
from sase.memory.episodes.storage import (
    EPISODE_JSON_FILE_NAME,
    EPISODE_LESSON_FILE_NAME,
)


def handle_episode_show(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    project = project_from_args(args)
    episode_dir = resolve_episode_dir(
        project,
        args.episode_id,
        projects_root,
        report_alias=True,
    )
    fmt = args.format
    if getattr(args, "json", False) and fmt != "agent":
        fmt = "json"

    if fmt == "json":
        print_file(episode_dir / EPISODE_JSON_FILE_NAME)
        return
    episode = load_episode(episode_dir)
    if fmt == "agent" and getattr(args, "json", False):
        print_json(agent_evidence_pack_json_dict(episode))
        return
    if fmt == "overview":
        lesson_path = episode_dir / EPISODE_LESSON_FILE_NAME
        if _is_legacy_episode(episode) and lesson_path.exists():
            print_file(lesson_path)
            return
        print(render_overview_text(episode), end="")
        return
    if fmt == "sources":
        print(render_sources_text(episode), end="")
        return
    if fmt == "timeline":
        print(render_timeline_text(episode), end="")
        return
    if fmt == "graph":
        print(render_graph_text(episode, edge_mode=args.edge_mode), end="")
        return
    if fmt == "agent":
        print(render_agent_text(episode), end="")
        return

    lesson_path = episode_dir / EPISODE_LESSON_FILE_NAME
    if lesson_path.exists():
        print_file(lesson_path)
        return
    print(render_lesson_markdown(episode), end="")


def _is_legacy_episode(episode: EpisodeWire) -> bool:
    return episode.status == "legacy" or not episode.component_key
