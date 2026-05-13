"""Dismissed agent bundle persistence and archive search entry points."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tui.models.agent import Agent


def has_dismissed_bundle(ctx: Any, raw_suffix: str) -> bool:
    """Return whether any bundle file exists for ``raw_suffix``.

    Checks both parent bundle names (``{suffix}.json``) and child bundle names
    (``{suffix}__c*.json``) across the current sharded layout and legacy
    top-level layout.
    """
    if any(path.is_file() for path in ctx._bundle_paths_for_suffixes({raw_suffix})):
        return True
    if ctx._find_bundle(f"{raw_suffix}.json") is not None:
        return True
    try:
        return bool(ctx._iter_bundle_paths(pattern=f"{raw_suffix}__c*.json"))
    except OSError:
        return False


def save_dismissed_bundle(ctx: Any, agent: Agent) -> bool:
    """Save a single agent bundle to its own file.

    Parent agents use ``{raw_suffix}.json``; child agents (workflow steps)
    use ``{raw_suffix}__c{step_index}.json`` to avoid overwriting the parent's
    bundle (they share the same raw_suffix).
    """
    if agent.raw_suffix is None:
        return False
    bundle = agent.to_bundle_dict()
    try:
        saved_path = ctx._save_dismissed_bundle_python(
            ctx._DISMISSED_BUNDLES_DIR, bundle
        )
    except OSError:
        return False

    try:
        from .dismissed_bundle_index import upsert_bundle_summary

        upsert_bundle_summary(ctx._DISMISSED_BUNDLES_DIR, saved_path, bundle)
    except (OSError, ValueError):
        pass
    return True


def rebuild_dismissed_bundle_index(ctx: Any) -> tuple[int, int]:
    """Rebuild the persistent dismissed bundle summary index."""
    from .dismissed_bundle_index import rebuild_index

    ctx._run_dismissed_archive_maintenance()
    result = rebuild_index(ctx._DISMISSED_BUNDLES_DIR)
    return result.indexed_rows, result.skipped_corrupt


def verify_dismissed_bundle_index(ctx: Any) -> dict[str, int | bool]:
    """Return diagnostics for the persistent dismissed bundle summary index."""
    from .dismissed_bundle_index import verify_index

    result = verify_index(ctx._DISMISSED_BUNDLES_DIR)
    return {
        "ok": result.ok,
        "indexed_rows": result.indexed_rows,
        "valid_bundles": result.valid_bundles,
        "corrupt_bundles": result.corrupt_bundles,
        "stale_rows": result.stale_rows,
        "missing_rows": result.missing_rows,
    }


def load_dismissed_bundle_summaries(
    ctx: Any,
    *,
    suffixes: set[str] | None = None,
    cl_name: str | None = None,
    project_name: str | None = None,
    top_level_only: bool = False,
    limit: int | None = None,
) -> list[Any]:
    """Load indexed dismissed bundle summaries, rebuilding if needed."""
    try:
        from .dismissed_bundle_index import query_summaries

        summaries = query_summaries(
            ctx._DISMISSED_BUNDLES_DIR,
            suffixes=suffixes,
            cl_name=cl_name,
            project_name=project_name,
            top_level_only=top_level_only,
            limit=limit,
        )
        if summaries is not None:
            return summaries
        ctx.rebuild_dismissed_bundle_index()
        return (
            query_summaries(
                ctx._DISMISSED_BUNDLES_DIR,
                suffixes=suffixes,
                cl_name=cl_name,
                project_name=project_name,
                top_level_only=top_level_only,
                limit=limit,
            )
            or []
        )
    except (OSError, ValueError, sqlite3.Error):
        return []


def ensure_dismissed_archive_ready(ctx: Any) -> None:
    """Run cold-start dismissed-bundle setup (migrations + index build)."""
    from .dismissed_bundle_index import archive_index_exists, rebuild_index

    ctx._run_dismissed_archive_maintenance()
    if not archive_index_exists(ctx._DISMISSED_BUNDLES_DIR):
        rebuild_index(ctx._DISMISSED_BUNDLES_DIR)


def mark_bundles_revived_by_suffixes(
    ctx: Any,
    suffixes: set[str],
    *,
    revived_at: str | None = None,
) -> int:
    """Preserve dismissed bundles after revive without archive lifecycle markers."""
    del revived_at
    if not suffixes:
        return 0
    return len(ctx._bundle_paths_for_suffixes(suffixes))


def bundle_paths_for_suffixes(ctx: Any, suffixes: set[str]) -> list[Path]:
    """Return parent and child bundle paths matching raw suffixes."""
    try:
        from .dismissed_bundle_index import query_bundle_paths_by_suffixes

        indexed_paths = query_bundle_paths_by_suffixes(
            ctx._DISMISSED_BUNDLES_DIR, suffixes
        )
    except (OSError, ValueError, sqlite3.Error):
        indexed_paths = None
    if indexed_paths:
        return [path for path in indexed_paths if path.is_file()]

    paths: list[Path] = []
    for suffix in suffixes:
        parent = ctx._find_bundle(f"{suffix}.json")
        if parent is not None:
            paths.append(parent)
        try:
            paths.extend(ctx._iter_bundle_paths(pattern=f"{suffix}__c*.json"))
        except OSError:
            continue
    return paths


def save_dismissed_bundle_python(root: Path, bundle: dict[str, Any]) -> Path:
    raw_suffix = bundle.get("raw_suffix")
    if not isinstance(raw_suffix, str) or not raw_suffix:
        raise OSError("dismissed bundle missing raw_suffix")
    is_child = bool(bundle.get("parent_workflow") or bundle.get("parent_timestamp"))
    if is_child:
        step_index = bundle.get("step_index")
        if not isinstance(step_index, int):
            step_index = 0
        filename = f"{raw_suffix}__c{step_index}.json"
    else:
        filename = f"{raw_suffix}.json"
    target = root / filename
    try:
        from .dismissed_agents_paths import bundle_shard_dir

        target = bundle_shard_dir(root, filename) / filename
    except (OSError, ValueError):
        pass
    write_json_file_atomic(target, bundle)
    return target


def write_json_file_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    fsync_dir(path.parent)


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def bundle_filename(agent: Agent) -> str:
    """Return the bundle filename for *agent*."""
    suffix = agent.raw_suffix
    if agent.is_workflow_child:
        idx = agent.step_index if agent.step_index is not None else 0
        return f"{suffix}__c{idx}.json"
    return f"{suffix}.json"


def load_dismissed_bundles(ctx: Any, suffixes: set[str] | None = None) -> list[Agent]:
    """Load dismissed agent bundles from per-agent files."""
    if suffixes is None:
        ctx._run_dismissed_archive_maintenance()
    else:
        ctx._maybe_migrate_bundles()
        ctx._maybe_shard_root_bundles()

    if not ctx._DISMISSED_BUNDLES_DIR.is_dir():
        return []

    bundle_paths: list[Path] = []
    if suffixes is not None:
        try:
            from .dismissed_bundle_index import query_bundle_paths_by_suffixes

            indexed_paths = query_bundle_paths_by_suffixes(
                ctx._DISMISSED_BUNDLES_DIR,
                suffixes,
            )
        except (OSError, ValueError):
            indexed_paths = None

        if indexed_paths:
            bundle_paths.extend(path for path in indexed_paths if path.is_file())
        else:
            bundle_paths.extend(ctx._bundle_paths_for_suffixes(suffixes))
    else:
        bundle_paths.extend(ctx._iter_bundle_paths())

    if not bundle_paths:
        return []

    from .tui.models._loaders._json_cache import get_loader_executor

    executor = get_loader_executor()
    results = executor.map(ctx._load_bundle_file, bundle_paths)
    return [agent for agent in results if agent is not None]


def load_bundle_file(filepath: Path) -> Agent | None:
    """Load a single Agent from a bundle JSON file."""
    from .tui.models._loaders._json_cache import load_json_cached
    from .tui.models.agent import Agent

    try:
        data = load_json_cached(filepath)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        agent = Agent.from_bundle_dict(data)
    except (KeyError, ValueError, TypeError):
        return None
    agent._dismissed_bundle_path = str(filepath)
    return agent
