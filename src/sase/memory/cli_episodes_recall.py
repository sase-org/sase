"""Recall handler for ``sase memory episodes recall``."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.core.episode_facade import episode_wire_schema_version
from sase.memory.cli_episodes_common import (
    canonical_index_rows_for_project,
    fail,
    print_json,
    project_from_args,
    validate_limit,
)
from sase.memory.episodes.recall import recall_episode_rows


def handle_episode_recall(
    args: argparse.Namespace,
    *,
    projects_root: Path | str | None,
) -> None:
    validate_limit(args.limit, "limit")
    project = project_from_args(args)
    try:
        matches = recall_episode_rows(
            canonical_index_rows_for_project(project, projects_root),
            args.query,
            projects_root=projects_root,
            limit=args.limit,
        )
    except ValueError as exc:
        fail(f"sase memory episodes recall: {exc}")

    if getattr(args, "json", False):
        print_json(
            {
                "matches": [match.to_json_dict() for match in matches],
                "project": project,
                "query": args.query,
                "schema_version": episode_wire_schema_version(),
            }
        )
        return

    if not matches:
        print(
            "No matching episodes. Try `list` to see what is stored, or "
            "`build` from a relevant agent."
        )
        return

    for match in matches:
        print(f"{match.episode_id}  score={match.score}  {match.title}")
        if match.lessons:
            for lesson in match.lessons:
                evidence = ", ".join(
                    f"{item.source_id}:{item.path}" if item.path else item.source_id
                    for item in lesson.evidence
                )
                suffix = f"  evidence={evidence}" if evidence else ""
                print(f"  - {lesson.lesson_id}: {lesson.text}{suffix}")
        elif match.excerpt:
            print(f"  {match.excerpt}")
