"""Dismissed agent bundle persistence and archive search entry points."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from datetime import datetime
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
        from .dismissed_bundle_index import next_archive_revision

        revision = next_archive_revision(ctx._DISMISSED_BUNDLES_DIR, bundle)
    except (OSError, ValueError, sqlite3.Error):
        existing = bundle.get("archive_revision")
        revision = existing if isinstance(existing, int) else 1

    saved_path: Path | None = None
    for _ in range(8):
        bundle["archive_revision"] = revision
        try:
            from sase.core.agent_cleanup_execution import try_save_dismissed_bundle

            result = try_save_dismissed_bundle(ctx._DISMISSED_BUNDLES_DIR, bundle)
            if result is not None:
                saved_path = Path(str(result["path"]))
                break
        except (FileExistsError, ValueError) as exc:
            if "already exists" in str(exc):
                revision += 1
                continue
            return False
        except OSError:
            return False

        try:
            saved_path = ctx._save_dismissed_bundle_python(
                ctx._DISMISSED_BUNDLES_DIR, bundle
            )
            break
        except FileExistsError:
            revision += 1
            continue
        except OSError:
            return False
    if saved_path is None:
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
    try:
        from sase.core.agent_archive_facade import try_verify_agent_archive_index

        rust_result = try_verify_agent_archive_index(ctx._DISMISSED_BUNDLES_DIR)
        if rust_result is not None:
            return rust_result
    except (OSError, ValueError):
        pass

    from .dismissed_bundle_index import verify_index

    result = verify_index(ctx._DISMISSED_BUNDLES_DIR)
    return {
        "ok": result.ok,
        "indexed_rows": result.indexed_rows,
        "valid_bundles": result.valid_bundles,
        "corrupt_bundles": result.corrupt_bundles,
        "stale_rows": result.stale_rows,
        "missing_rows": result.missing_rows,
        "fts_missing_rows": result.fts_missing_rows,
        "fts_orphan_rows": result.fts_orphan_rows,
        "payload_hash_mismatches": result.payload_hash_mismatches,
        "orphan_visibility_rows": result.orphan_visibility_rows,
        "orphan_revision_rows": result.orphan_revision_rows,
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
    """Run cold-start archive setup (migrations + index build)."""
    from .dismissed_bundle_index import archive_index_exists, rebuild_index

    ctx._run_dismissed_archive_maintenance()
    if not archive_index_exists(ctx._DISMISSED_BUNDLES_DIR):
        rebuild_index(ctx._DISMISSED_BUNDLES_DIR)


def search_dismissed_archive(
    ctx: Any,
    query: str,
    *,
    limit: int = 50,
    cursor: int | None = None,
) -> Any:
    """Search dismissed bundle summaries via the archive query planner."""
    from .agent_query.archive_planner import search_archive

    ctx.ensure_dismissed_archive_ready()
    return search_archive(ctx._DISMISSED_BUNDLES_DIR, query, limit=limit, cursor=cursor)


def mark_bundles_revived_by_suffixes(
    ctx: Any,
    suffixes: set[str],
    *,
    revived_at: str | None = None,
) -> int:
    """Mark preserved dismissed bundles as revived without deleting them."""
    if not suffixes:
        return 0
    timestamp = revived_at or datetime.now().isoformat()
    paths = ctx._bundle_paths_for_suffixes(suffixes)
    try:
        from sase.core.agent_archive_facade import (
            try_mark_agent_archive_bundles_revived,
        )
        from sase.core.agent_archive_wire import AgentArchiveReviveMarkRequestWire

        report = try_mark_agent_archive_bundles_revived(
            ctx._DISMISSED_BUNDLES_DIR,
            AgentArchiveReviveMarkRequestWire(
                bundle_paths=[str(path) for path in paths],
                revived_at=timestamp,
            ),
        )
        if report is not None:
            return int(report.get("changed", 0))
    except (OSError, ValueError):
        pass

    changed = 0
    for path in paths:
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(bundle, dict):
                continue
            bundle["revived_at"] = timestamp
            times_revived = bundle.get("times_revived", 0)
            if not isinstance(times_revived, int):
                try:
                    times_revived = int(times_revived)
                except (TypeError, ValueError):
                    times_revived = 0
            bundle["times_revived"] = max(0, times_revived) + 1
            ctx._write_json_file_atomic(path, bundle)
            try:
                from .dismissed_bundle_index import upsert_bundle_summary

                upsert_bundle_summary(ctx._DISMISSED_BUNDLES_DIR, path, bundle)
            except (OSError, ValueError, sqlite3.Error):
                pass
            changed += 1
        except (OSError, json.JSONDecodeError):
            continue
    return changed


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
    matched = {path.resolve(strict=False) for path in paths}
    try:
        for path in ctx._iter_bundle_paths():
            if path.resolve(strict=False) in matched:
                continue
            if path.name != "bundle.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("raw_suffix") in suffixes:
                paths.append(path)
                matched.add(path.resolve(strict=False))
    except OSError:
        pass
    return paths


def save_dismissed_bundle_python(root: Path, bundle: dict[str, Any]) -> Path:
    from .dismissed_bundle_index import archive_bundle_path

    revision = bundle.get("archive_revision")
    if not isinstance(revision, int):
        revision = 1
    target = archive_bundle_path(root, bundle, revision)
    final_dir = target.parent
    shard_dir = final_dir.parent
    shard_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = shard_dir / f".{final_dir.name}.tmp.{os.getpid()}.{time.time_ns()}"
    tmp_dir.mkdir(mode=0o700)
    try:
        write_json_file_atomic(tmp_dir / "bundle.json", bundle)
        os.replace(tmp_dir, final_dir)
        fsync_dir(shard_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
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
                latest_only=True,
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
