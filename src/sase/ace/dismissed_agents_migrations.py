"""One-shot migrations for dismissed agent bundle archives."""

from __future__ import annotations

import json
from typing import Any

_ROOT_SHARD_MARKER_NAME = ".root_bundles_sharded"
_CHILD_COLLISION_MARKER_NAME = ".child_collision_fixed"


def maybe_migrate_bundles(ctx: Any) -> None:
    """One-time migration from monolithic bundles file to per-agent files."""
    old_bundles_file = ctx._old_bundles_file()
    if not old_bundles_file.exists():
        return

    from .tui.models.agent import Agent

    try:
        with open(old_bundles_file) as f:
            data = json.load(f)
        if not isinstance(data, list):
            old_bundles_file.unlink()
            return

        ctx.dismissed_bundles_dir().mkdir(parents=True, exist_ok=True)
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                agent = Agent.from_bundle_dict(entry)
                ctx.save_dismissed_bundle(agent)
            except (KeyError, ValueError, TypeError):
                continue

        old_bundles_file.unlink()
    except (OSError, json.JSONDecodeError):
        pass


def run_dismissed_archive_maintenance(ctx: Any) -> None:
    """Run startup-safe, one-shot dismissed archive migrations."""
    ctx._maybe_migrate_bundles()
    ctx._maybe_shard_root_bundles()
    ctx._maybe_fix_child_collisions()


def maybe_shard_root_bundles(ctx: Any) -> None:
    """One-time migration: move pre-shard root bundle files into YYYYMM dirs."""
    bundles_dir = ctx.dismissed_bundles_dir()
    marker = bundles_dir / _ROOT_SHARD_MARKER_NAME
    if marker.exists():
        return
    if not bundles_dir.is_dir():
        return

    try:
        for filepath in list(bundles_dir.glob("*.json")):
            if not filepath.is_file():
                continue
            destination = ctx._bundle_shard_dir(filepath.name) / filepath.name
            if destination == filepath:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                filepath.rename(destination)
        marker.touch()
    except OSError:
        pass


def maybe_fix_child_collisions(ctx: Any) -> None:
    """One-time migration: rename child bundles that overwrote their parent."""
    bundles_dir = ctx.dismissed_bundles_dir()
    marker = bundles_dir / _CHILD_COLLISION_MARKER_NAME
    if marker.exists():
        return
    if not bundles_dir.is_dir():
        return

    try:
        for filepath in list(ctx._iter_bundle_paths()):
            if filepath.name == "bundle.json" or "__c" in filepath.stem:
                continue
            agent = ctx._load_bundle_file(filepath)
            if agent is None:
                continue
            if agent.is_workflow_child:
                new_name = ctx._bundle_filename(agent)
                new_path = filepath.parent / new_name
                if not new_path.exists():
                    filepath.rename(new_path)
    except OSError:
        pass

    try:
        bundles_dir.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass
