"""Dismissed agent bundle persistence and archive search entry points."""

from __future__ import annotations

from concurrent.futures import CancelledError
from functools import lru_cache
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tui.models.agent import Agent


@lru_cache(maxsize=1_024)
def _completed_import_transaction(project_key: str, transaction_key: str) -> bool:
    from sase.agents_sync.v2_importer import import_transaction_is_complete

    return import_transaction_is_complete(project_key, transaction_key)


def _imported_bundle_is_visible(data: dict[str, Any]) -> bool:
    transaction_key = data.get("imported_transaction_key")
    if not isinstance(transaction_key, str) or not transaction_key:
        return True
    project_file = data.get("project_file")
    if not isinstance(project_file, str) or not project_file:
        return False
    project_key = Path(project_file).expanduser().parent.name
    return bool(project_key) and _completed_import_transaction(
        project_key,
        transaction_key,
    )


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
        bundles_dir = ctx.dismissed_bundles_dir()
        saved_path = ctx._save_dismissed_bundle_python(bundles_dir, bundle)
    except OSError:
        return False

    try:
        from .dismissed_bundle_index import upsert_bundle_summary

        upsert_bundle_summary(bundles_dir, saved_path, bundle)
    except (OSError, ValueError):
        pass
    return True


def rebuild_dismissed_bundle_index(ctx: Any) -> tuple[int, int]:
    """Rebuild the persistent dismissed bundle summary index."""
    from .dismissed_bundle_index import rebuild_index

    ctx._run_dismissed_archive_maintenance()
    result = rebuild_index(ctx.dismissed_bundles_dir())
    return result.indexed_rows, result.skipped_corrupt


def verify_dismissed_bundle_index(ctx: Any) -> dict[str, int | bool]:
    """Return diagnostics for the persistent dismissed bundle summary index."""
    from .dismissed_bundle_index import verify_index

    result = verify_index(ctx.dismissed_bundles_dir())
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
    offset: int | None = None,
) -> list[Any]:
    """Load indexed dismissed bundle summaries, rebuilding if needed."""
    try:
        from .dismissed_bundle_index import query_summaries

        bundles_dir = ctx.dismissed_bundles_dir()
        summaries = query_summaries(
            bundles_dir,
            suffixes=suffixes,
            cl_name=cl_name,
            project_name=project_name,
            top_level_only=top_level_only,
            limit=limit,
            offset=offset,
        )
        if summaries is not None:
            return summaries
        ctx.rebuild_dismissed_bundle_index()
        return (
            query_summaries(
                bundles_dir,
                suffixes=suffixes,
                cl_name=cl_name,
                project_name=project_name,
                top_level_only=top_level_only,
                limit=limit,
                offset=offset,
            )
            or []
        )
    except (OSError, ValueError, sqlite3.Error):
        return []


def load_dismissed_bundle_identities(ctx: Any) -> set[tuple[str, str, str | None]]:
    """Load distinct dismissed-bundle identities, rebuilding if needed."""
    try:
        from .dismissed_bundle_index import query_summary_identities

        bundles_dir = ctx.dismissed_bundles_dir()
        identities = query_summary_identities(bundles_dir)
        if identities is not None:
            return identities
        ctx.rebuild_dismissed_bundle_index()
        return query_summary_identities(bundles_dir) or set()
    except (OSError, ValueError, sqlite3.Error):
        return set()


def ensure_dismissed_archive_ready(ctx: Any) -> None:
    """Run cold-start dismissed-bundle setup (migrations + index build)."""
    from .dismissed_bundle_index import archive_index_exists, rebuild_index

    ctx._run_dismissed_archive_maintenance()
    bundles_dir = ctx.dismissed_bundles_dir()
    if not archive_index_exists(bundles_dir):
        rebuild_index(bundles_dir)


def mark_bundles_revived_by_suffixes(
    ctx: Any,
    suffixes: set[str],
    *,
    revived_at: str | None = None,
) -> int:
    """Purge the dismissed bundles for revived agents.

    Revive restores the live on-disk artifacts, so the dismissed bundle is
    redundant. Worse, the artifact-index dismissed projection unions the
    in-memory dismissed set with *every* dismissed-bundle summary, so a
    lingering bundle re-hides the revived agent on the next projection rebuild
    (``sase agent index gc``, cold-start archive maintenance, or a
    drift-triggered non-authoritative sync). Delete both the bundle files and
    their summary index rows -- mirroring the name-wipe path
    (``agent/names/_wipe.py``) -- so the projection stops re-deriving the
    revived identities. If the user re-dismisses, the dismiss flow writes a
    fresh bundle.

    Returns the number of bundle files removed.
    """
    del revived_at
    if not suffixes:
        return 0

    from .dismissed_bundle_index import delete_bundle_summaries_for_suffixes

    removed = 0
    for path in ctx._bundle_paths_for_suffixes(suffixes):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        removed += 1

    delete_bundle_summaries_for_suffixes(ctx.dismissed_bundles_dir(), suffixes)
    return removed


def purge_revived_dismissed_bundles(ctx: Any) -> int:
    """Purge dismissed bundles whose identities are no longer dismissed.

    One-time reconciliation for archives that accumulated stale bundles before
    revive learned to purge them. A bundle whose ``raw_suffix`` is absent from
    every identity in ``dismissed_agents.json`` belongs to an already-revived
    agent; its lingering summary keeps re-feeding the dismissed projection.
    Purging by suffix is parent/child safe: a suffix is treated as orphaned
    only when *no* dismissed identity still references it, so bundles for
    agents that remain dismissed are preserved.

    Returns the number of bundle files removed.
    """
    from .dismissed_agents_state import load_dismissed_agents

    dismissed = load_dismissed_agents(ctx._dismissed_agents_file())
    dismissed_suffixes = {raw_suffix for (_, _, raw_suffix) in dismissed if raw_suffix}

    orphan_suffixes: set[str] = set()
    for summary in load_dismissed_bundle_summaries(ctx, limit=None):
        raw_suffix = getattr(summary, "raw_suffix", None)
        if raw_suffix and raw_suffix not in dismissed_suffixes:
            orphan_suffixes.add(raw_suffix)

    return mark_bundles_revived_by_suffixes(ctx, orphan_suffixes)


def bundle_paths_for_suffixes(ctx: Any, suffixes: set[str]) -> list[Path]:
    """Return parent and child bundle paths matching raw suffixes."""
    try:
        from .dismissed_bundle_index import query_bundle_paths_by_suffixes

        indexed_paths = query_bundle_paths_by_suffixes(
            ctx.dismissed_bundles_dir(), suffixes
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

    bundles_dir = ctx.dismissed_bundles_dir()
    if not bundles_dir.is_dir():
        return []

    bundle_paths: list[Path] = []
    if suffixes is not None:
        try:
            from .dismissed_bundle_index import query_bundle_paths_by_suffixes

            indexed_paths = query_bundle_paths_by_suffixes(
                bundles_dir,
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

    return _load_bundle_paths(ctx, bundle_paths)


def _load_bundle_paths(ctx: Any, bundle_paths: list[Path]) -> list[Agent]:
    """Load dismissed agents from already-resolved bundle paths."""
    from sase.project_display_names import attach_project_display_names

    _completed_import_transaction.cache_clear()
    from .tui.models._loaders._json_cache import (
        get_loader_executor,
        is_loader_executor_shutdown_error,
    )

    executor = get_loader_executor()
    agents: list[Agent] = []
    try:
        for agent in executor.map(ctx._load_bundle_file, bundle_paths):
            if agent is not None:
                agents.append(agent)
    except CancelledError:
        attach_project_display_names(agents)
        return agents
    except RuntimeError as exc:
        if is_loader_executor_shutdown_error(exc):
            attach_project_display_names(agents)
            return agents
        raise
    finally:
        _completed_import_transaction.cache_clear()
    attach_project_display_names(agents)
    return agents


def load_dismissed_bundles_page(
    ctx: Any,
    *,
    cl_name: str | None = None,
    project_name: str | None = None,
    limit: int = 250,
    offset: int = 0,
) -> tuple[list[Agent], bool]:
    """Load one recency-ordered page of top-level dismissed bundles.

    The page unit is visible parent rows. Children for those parents are loaded
    with the same suffixes so workflow step counts and previews are complete for
    every loaded page.
    """
    page_limit = max(0, limit)
    page_offset = max(0, offset)
    if page_offset == 0:
        ensure_dismissed_archive_ready(ctx)
    if page_limit == 0:
        return [], True

    summaries = load_dismissed_bundle_summaries(
        ctx,
        cl_name=cl_name,
        project_name=project_name,
        top_level_only=True,
        limit=page_limit + 1,
        offset=page_offset,
    )
    exhausted = len(summaries) <= page_limit
    page_summaries = summaries[:page_limit]
    suffixes = {
        summary.raw_suffix
        for summary in page_summaries
        if getattr(summary, "raw_suffix", None)
    }
    if not suffixes:
        return [], exhausted

    bundle_paths = bundle_paths_for_suffixes(ctx, suffixes)
    agents = _load_bundle_paths(ctx, bundle_paths) if bundle_paths else []
    for agent in agents:
        agent._loaded_from_dismissed_bundle = True
    return agents, exhausted


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
    if not _imported_bundle_is_visible(data):
        return None
    try:
        agent = Agent.from_bundle_dict(data)
    except (KeyError, ValueError, TypeError):
        return None
    agent._dismissed_bundle_path = str(filepath)
    return agent
