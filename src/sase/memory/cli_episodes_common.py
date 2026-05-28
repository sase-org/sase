"""Shared helpers for ``sase memory episodes`` CLI handlers."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any, NoReturn

from sase.core.episode_wire import (
    EpisodeStorageIndexRowWire,
    EpisodeVerifyReportWire,
    EpisodeWire,
    episode_wire_from_dict,
)
from sase.main.init_memory.config import project_memory_name
from sase.memory.episodes.identity import (
    EpisodeIdResolution,
    canonical_episode_ids,
    episode_id_reference_map,
)
from sase.memory.episodes.index import project_episodes_dir
from sase.memory.episodes.inventory import canonical_index_rows
from sase.memory.episodes.storage import EPISODE_JSON_FILE_NAME
from sase.memory.episodes.verify import verify_episode


def project_from_args(args: argparse.Namespace) -> str:
    project = getattr(args, "project", None)
    if project is not None and project.strip():
        return project.strip()
    return project_memory_name(Path.cwd())


def resolve_episode_dir(
    project: str,
    episode_id: str,
    projects_root: Path | str | None,
    *,
    report_alias: bool = False,
) -> Path:
    resolution = _resolve_episode_reference(project, episode_id, projects_root)
    if report_alias:
        _report_alias_resolution(resolution)
    return project_episodes_dir(project, projects_root=projects_root) / (
        resolution.episode_id
    )


def _resolve_episode_reference(
    project: str,
    episode_id: str,
    projects_root: Path | str | None,
) -> EpisodeIdResolution:
    requested = episode_id.strip()
    if not requested:
        fail("sase memory episodes: episode id must not be empty")
    references = episode_id_reference_map(project, projects_root=projects_root)
    exact = references.get(requested)
    if exact is not None:
        return replace(exact, requested_id=requested)
    prefix_matches = [item for item in references if item.startswith(requested)]
    if len(prefix_matches) == 1:
        resolution = references[prefix_matches[0]]
        return replace(resolution, requested_id=requested)
    if len(prefix_matches) > 1:
        canonical_targets = {references[item].episode_id for item in prefix_matches}
        if len(canonical_targets) == 1:
            canonical_match = next(
                (
                    item
                    for item in sorted(prefix_matches)
                    if not references[item].is_alias
                ),
                sorted(prefix_matches)[0],
            )
            resolution = references[canonical_match]
            return replace(resolution, requested_id=requested)
        fail(
            "sase memory episodes: episode id prefix "
            f"`{requested}` is ambiguous: {', '.join(prefix_matches[:5])}"
        )
    ids = sorted(references)
    available = ", ".join(ids[:5]) if ids else "list"
    fail(
        f"sase memory episodes: No episode found for id `{requested}`. "
        f"Available ids: {available}."
    )
    raise AssertionError("unreachable")


def _report_alias_resolution(resolution: EpisodeIdResolution) -> None:
    if not resolution.is_alias:
        return
    reason = f" ({resolution.alias_reason})" if resolution.alias_reason else ""
    print(
        "sase memory episodes: "
        f"`{resolution.matched_id}` is an alias for `{resolution.episode_id}`{reason}",
        file=sys.stderr,
    )


def canonical_index_rows_for_project(
    project: str,
    projects_root: Path | str | None,
) -> list[EpisodeStorageIndexRowWire]:
    return canonical_index_rows(project, projects_root)


def all_episode_dirs(
    project: str,
    projects_root: Path | str | None,
) -> list[Path]:
    return [
        project_episodes_dir(project, projects_root=projects_root) / episode_id
        for episode_id in canonical_episode_ids(project, projects_root=projects_root)
    ]


def load_episode(episode_dir: Path) -> EpisodeWire:
    episode_path = episode_dir / EPISODE_JSON_FILE_NAME
    try:
        data = json.loads(episode_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"sase memory episodes: missing episode.json under {episode_dir}")
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"sase memory episodes: failed to read {episode_path}: {exc}")
    try:
        return episode_wire_from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        fail(f"sase memory episodes: invalid episode.json under {episode_dir}: {exc}")
    raise AssertionError("unreachable")


def verify_episode_dir(episode_dir: Path) -> EpisodeVerifyReportWire:
    return verify_episode(load_episode(episode_dir))


def print_file(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"sase memory episodes: failed to read {path}: {exc}")
    print(text, end="" if text.endswith("\n") else "\n")


def print_json(payload: Any) -> None:
    json.dump(payload, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


def validate_limit(value: int | None, label: str) -> None:
    if value is not None and value < 1:
        fail(f"sase memory episodes: {label} must be >= 1")


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(1)
