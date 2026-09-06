"""Event-stream loading, stage reads, and regenerable-conflict resolution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .conflict_resolver_git import (
    git_add,
    git_rm,
    read_git_show,
    unmerged_stages,
    upstream_and_local_stages,
)


def load_worktree_streams(
    beads_dir: Path,
    repo_root: Path,
    conflicted_paths: set[str],
) -> dict[str, dict[str, Any]]:
    streams_dir = beads_dir / "events" / "streams"
    streams: dict[str, dict[str, Any]] = {}
    if not streams_dir.is_dir():
        return streams
    for path in sorted(streams_dir.glob("*.jsonl")):
        rel = path.relative_to(repo_root).as_posix()
        if rel in conflicted_paths:
            continue
        streams[path.stem] = _parse_stream_text(
            path.read_text(encoding="utf-8"), path.stem
        )
    return streams


def read_stage_stream(
    repo_root: Path,
    path: str,
    stage: int,
    stream_id: str,
    stages: frozenset[int],
) -> dict[str, Any]:
    if stage not in stages:
        # A genuinely absent stage (add/add conflicts have no base) is empty.
        return empty_stream(stream_id)
    text = read_git_show(repo_root, stage, path)
    return _parse_stream_text(text, stream_id)


def resolve_regenerable_conflicts(repo_root: Path, paths: list[str]) -> list[str]:
    resolved: list[str] = []
    for path in sorted(paths):
        _resolve_regenerable_conflict(repo_root, path)
        resolved.append(path)
    return resolved


def _resolve_regenerable_conflict(repo_root: Path, path: str) -> None:
    upstream_stage, _local_stage = upstream_and_local_stages(repo_root)
    stages = unmerged_stages(repo_root, path)
    if upstream_stage not in stages:
        git_rm(repo_root, path)
        return

    text = read_git_show(repo_root, upstream_stage, path)
    target = repo_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git_add(repo_root, [path])


def _parse_stream_text(text: str, stream_id: str) -> dict[str, Any]:
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    return {"stream_id": stream_id, "root_issue_id": stream_id, "events": events}


def empty_stream(stream_id: str) -> dict[str, Any]:
    return {"stream_id": stream_id, "root_issue_id": stream_id, "events": []}
