"""Merge logic for conflicted bead-store ``config.json`` files."""

from __future__ import annotations

import json
from pathlib import Path

from .conflict_resolver_git import (
    read_git_show,
    unmerged_stages,
    upstream_and_local_stages,
)


def merged_conflicted_config(repo_root: Path, path: str) -> dict[str, object] | None:
    """Merge a conflicted store config.json when only next_counter diverges."""
    stages = unmerged_stages(repo_root, path)
    base = _read_config_stage(repo_root, path, 1, stages, absent={})
    upstream_stage, local_stage = upstream_and_local_stages(repo_root)
    upstream = _read_config_stage(repo_root, path, upstream_stage, stages)
    local = _read_config_stage(repo_root, path, local_stage, stages)
    if base is None or upstream is None or local is None:
        return None
    if _config_without_counter(local) != _config_without_counter(upstream):
        return None
    counters = _next_counters(base, local, upstream)
    if counters is None:
        return None
    merged = dict(local)
    if counters:
        merged["next_counter"] = max(counters)
    elif "next_counter" in merged:
        del merged["next_counter"]
    return merged


def config_with_allocated_counter(
    config: dict[str, object], allocated_next: int
) -> dict[str, object]:
    updated = dict(config)
    current = updated.get("next_counter")
    candidates = [allocated_next]
    if isinstance(current, int) and not isinstance(current, bool):
        candidates.append(current)
    updated["next_counter"] = max(candidates)
    return updated


def _config_without_counter(config: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in config.items() if key != "next_counter"}


def _next_counters(*configs: dict[str, object]) -> list[int] | None:
    values: list[int] = []
    for config in configs:
        if "next_counter" not in config:
            continue
        value = config["next_counter"]
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        values.append(value)
    return values


def _read_config_stage(
    repo_root: Path,
    path: str,
    stage: int,
    stages: frozenset[int],
    *,
    absent: dict[str, object] | None = None,
) -> dict[str, object] | None:
    if stage not in stages:
        return absent
    text = read_git_show(repo_root, stage, path)
    return _parse_config_object(text)


def _parse_config_object(text: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(key): value for key, value in parsed.items()}
