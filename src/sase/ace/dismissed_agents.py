"""Persistent tracking of dismissed agents across sessions."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.paths import parse_filename_timestamp

if TYPE_CHECKING:
    from .tui.models.agent import Agent, AgentType

_DISMISSED_AGENTS_FILE = Path.home() / ".sase" / "dismissed_agents.json"
_DISMISSED_BUNDLES_DIR = Path.home() / ".sase" / "dismissed_bundles"
_OLD_BUNDLES_FILE = Path.home() / ".sase" / "dismissed_agent_bundles.json"

_SHARD_DIR_RE = re.compile(r"^\d{6}$")


def _bundle_shard_dir(filename: str) -> Path:
    """Return the YYYYMM shard subdir under ``_DISMISSED_BUNDLES_DIR`` for a bundle.

    Bundle filenames start with a 14-digit timestamp (``raw_suffix``);
    children append ``__c<idx>`` before ``.json``.  If the timestamp
    can't be parsed, fall back to ``now()`` so the file still lands in
    a valid shard.
    """
    ts = parse_filename_timestamp(filename) or datetime.now()
    return _DISMISSED_BUNDLES_DIR / ts.strftime("%Y%m")


def _iter_bundle_paths(pattern: str = "*.json") -> list[Path]:
    """Yield bundle file paths across all shards and the legacy top level."""
    if not _DISMISSED_BUNDLES_DIR.is_dir():
        return []
    results: list[Path] = []
    for entry in _DISMISSED_BUNDLES_DIR.iterdir():
        if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
            results.extend(path for path in entry.glob(pattern) if path.is_file())
            if pattern == "*.json":
                results.extend(
                    path for path in entry.glob("*/bundle.json") if path.is_file()
                )
    # Legacy (pre-migration) files directly in the root.
    for p in _DISMISSED_BUNDLES_DIR.glob(pattern):
        if p.is_file():
            results.append(p)
    return results


def _find_bundle(filename: str) -> Path | None:
    """Return the on-disk path for ``filename`` — shard fast path, then scan."""
    ts = parse_filename_timestamp(filename)
    if ts is not None:
        candidate = _DISMISSED_BUNDLES_DIR / ts.strftime("%Y%m") / filename
        if candidate.is_file():
            return candidate
    legacy = _DISMISSED_BUNDLES_DIR / filename
    if legacy.is_file():
        return legacy
    if _DISMISSED_BUNDLES_DIR.is_dir():
        for entry in _DISMISSED_BUNDLES_DIR.iterdir():
            if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
                candidate = entry / filename
                if candidate.is_file():
                    return candidate
    return None


def has_dismissed_bundle(raw_suffix: str) -> bool:
    """Return whether any bundle file exists for ``raw_suffix``.

    Checks both parent bundle names (``{suffix}.json``) and child bundle names
    (``{suffix}__c*.json``) across the current sharded layout and legacy
    top-level layout.
    """
    if any(path.is_file() for path in _bundle_paths_for_suffixes({raw_suffix})):
        return True
    if _find_bundle(f"{raw_suffix}.json") is not None:
        return True
    try:
        return bool(_iter_bundle_paths(pattern=f"{raw_suffix}__c*.json"))
    except OSError:
        return False


def load_dismissed_agents() -> set[tuple[AgentType, str, str | None]]:
    """Load dismissed agent identities from disk.

    Returns:
        Set of (AgentType, cl_name, raw_suffix) tuples.
    """
    from .tui.models.agent import AgentType

    if not _DISMISSED_AGENTS_FILE.exists():
        return set()

    try:
        with open(_DISMISSED_AGENTS_FILE) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return set()

        result: set[tuple[AgentType, str, str | None]] = set()
        for entry in data:
            if not isinstance(entry, list) or len(entry) != 3:
                continue
            try:
                agent_type = AgentType(entry[0])
            except ValueError:
                continue
            cl_name = entry[1]
            raw_suffix = entry[2]
            if not isinstance(cl_name, str):
                continue
            if raw_suffix is not None and not isinstance(raw_suffix, str):
                continue
            result.add((agent_type, cl_name, raw_suffix))
        return result
    except (OSError, json.JSONDecodeError):
        return set()


def save_dismissed_agents(
    dismissed: set[tuple[AgentType, str, str | None]],
) -> bool:
    """Save dismissed agent identities to disk.

    Args:
        dismissed: Set of (AgentType, cl_name, raw_suffix) tuples.

    Returns:
        True if saved successfully, False otherwise.
    """
    entries = [
        {"agent_type": agent_type.value, "cl_name": cl_name, "raw_suffix": raw_suffix}
        for agent_type, cl_name, raw_suffix in sorted(
            dismissed, key=lambda item: (item[0].value, item[1], item[2] or "")
        )
    ]
    try:
        from sase.core.agent_cleanup_execution import (
            try_save_dismissed_agents_index,
        )

        if try_save_dismissed_agents_index(_DISMISSED_AGENTS_FILE, entries):
            return True
    except (OSError, ValueError):
        return False

    try:
        _DISMISSED_AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        legacy_entries = [
            [entry["agent_type"], entry["cl_name"], entry["raw_suffix"]]
            for entry in entries
        ]
        with open(_DISMISSED_AGENTS_FILE, "w") as f:
            json.dump(legacy_entries, f, indent=2)
        return True
    except OSError:
        return False


def save_dismissed_bundle(agent: Agent) -> bool:
    """Save a single agent bundle to its own file.

    Parent agents use ``{raw_suffix}.json``; child agents (workflow steps)
    use ``{raw_suffix}__c{step_index}.json`` to avoid overwriting the
    parent's bundle (they share the same raw_suffix).

    Args:
        agent: The Agent to serialize. Must have a non-None raw_suffix.

    Returns:
        True if saved successfully, False otherwise.
    """
    if agent.raw_suffix is None:
        return False
    bundle = agent.to_bundle_dict()
    saved_path: Path | None = None
    for _ in range(8):
        try:
            from .dismissed_bundle_index import next_archive_revision

            bundle["archive_revision"] = next_archive_revision(
                _DISMISSED_BUNDLES_DIR,
                bundle,
            )
        except (OSError, ValueError, sqlite3.Error):
            revision = bundle.get("archive_revision")
            bundle["archive_revision"] = revision if isinstance(revision, int) else 1

        try:
            from sase.core.agent_cleanup_execution import try_save_dismissed_bundle

            result = try_save_dismissed_bundle(_DISMISSED_BUNDLES_DIR, bundle)
            if result is not None:
                saved_path = Path(str(result["path"]))
                break
        except (FileExistsError, ValueError) as exc:
            if "already exists" in str(exc):
                continue
            return False
        except OSError:
            return False

        try:
            saved_path = _save_dismissed_bundle_python(_DISMISSED_BUNDLES_DIR, bundle)
            break
        except FileExistsError:
            continue
        except OSError:
            return False
    if saved_path is None:
        return False

    try:
        from .dismissed_bundle_index import upsert_bundle_summary

        upsert_bundle_summary(_DISMISSED_BUNDLES_DIR, saved_path, bundle)
    except (OSError, ValueError):
        pass
    return True


def rebuild_dismissed_bundle_index() -> tuple[int, int]:
    """Rebuild the persistent dismissed bundle summary index.

    Returns:
        ``(indexed_rows, skipped_corrupt)``.
    """
    from .dismissed_bundle_index import rebuild_index

    _run_dismissed_archive_maintenance()
    result = rebuild_index(_DISMISSED_BUNDLES_DIR)
    return result.indexed_rows, result.skipped_corrupt


def verify_dismissed_bundle_index() -> dict[str, int | bool]:
    """Return diagnostics for the persistent dismissed bundle summary index."""
    from .dismissed_bundle_index import verify_index

    result = verify_index(_DISMISSED_BUNDLES_DIR)
    return {
        "ok": result.ok,
        "indexed_rows": result.indexed_rows,
        "valid_bundles": result.valid_bundles,
        "corrupt_bundles": result.corrupt_bundles,
        "stale_rows": result.stale_rows,
        "missing_rows": result.missing_rows,
    }


def load_dismissed_bundle_summaries(
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
            _DISMISSED_BUNDLES_DIR,
            suffixes=suffixes,
            cl_name=cl_name,
            project_name=project_name,
            top_level_only=top_level_only,
            limit=limit,
        )
        if summaries is not None:
            return summaries
        rebuild_dismissed_bundle_index()
        return (
            query_summaries(
                _DISMISSED_BUNDLES_DIR,
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


def search_dismissed_archive(
    query: str,
    *,
    limit: int = 50,
    cursor: int | None = None,
) -> Any:
    """Search dismissed bundle summaries via the archive query planner."""

    _run_dismissed_archive_maintenance()
    from .agent_query.archive_planner import search_archive
    from .dismissed_bundle_index import archive_index_exists, rebuild_index

    if not archive_index_exists(_DISMISSED_BUNDLES_DIR):
        rebuild_index(_DISMISSED_BUNDLES_DIR)
    return search_archive(_DISMISSED_BUNDLES_DIR, query, limit=limit, cursor=cursor)


def mark_bundles_revived_by_suffixes(
    suffixes: set[str],
    *,
    revived_at: str | None = None,
) -> int:
    """Mark preserved dismissed bundles as revived without deleting them."""

    if not suffixes:
        return 0
    timestamp = revived_at or datetime.now().isoformat()
    paths = _bundle_paths_for_suffixes(suffixes)
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
            _write_json_file_atomic(path, bundle)
            try:
                from .dismissed_bundle_index import upsert_bundle_summary

                upsert_bundle_summary(_DISMISSED_BUNDLES_DIR, path, bundle)
            except (OSError, ValueError, sqlite3.Error):
                pass
            changed += 1
        except (OSError, json.JSONDecodeError):
            continue
    return changed


def _bundle_paths_for_suffixes(suffixes: set[str]) -> list[Path]:
    """Return parent and child bundle paths matching raw suffixes."""

    try:
        from .dismissed_bundle_index import query_bundle_paths_by_suffixes

        indexed_paths = query_bundle_paths_by_suffixes(_DISMISSED_BUNDLES_DIR, suffixes)
    except (OSError, ValueError, sqlite3.Error):
        indexed_paths = None
    if indexed_paths:
        return [path for path in indexed_paths if path.is_file()]

    paths: list[Path] = []
    for suffix in suffixes:
        parent = _find_bundle(f"{suffix}.json")
        if parent is not None:
            paths.append(parent)
        try:
            paths.extend(_iter_bundle_paths(pattern=f"{suffix}__c*.json"))
        except OSError:
            continue
    matched = {path.resolve(strict=False) for path in paths}
    try:
        for path in _iter_bundle_paths():
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


def _save_dismissed_bundle_python(root: Path, bundle: dict[str, Any]) -> Path:
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
        _write_json_file_atomic(tmp_dir / "bundle.json", bundle)
        os.replace(tmp_dir, final_dir)
        _fsync_dir(shard_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return target


def _write_json_file_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _bundle_filename(agent: Agent) -> str:
    """Return the bundle filename for *agent*.

    Child agents get a ``__c{step_index}`` suffix to avoid colliding with
    their parent, which shares the same ``raw_suffix``.
    """
    suffix = agent.raw_suffix
    if agent.is_workflow_child:
        idx = agent.step_index if agent.step_index is not None else 0
        return f"{suffix}__c{idx}.json"
    return f"{suffix}.json"


def load_dismissed_bundles(suffixes: set[str] | None = None) -> list[Agent]:
    """Load dismissed agent bundles from per-agent files.

    Args:
        suffixes: If provided, load only files matching these raw_suffixes.
                  If None, load all bundle files in the directory.

    Returns:
        List of Agent objects reconstructed from bundle files.
    """
    if suffixes is None:
        _run_dismissed_archive_maintenance()
    else:
        _maybe_migrate_bundles()
        _maybe_shard_root_bundles()

    if not _DISMISSED_BUNDLES_DIR.is_dir():
        return []

    # Collect the list of bundle files to load, then read them in parallel.
    bundle_paths: list[Path] = []
    if suffixes is not None:
        try:
            from .dismissed_bundle_index import query_bundle_paths_by_suffixes

            indexed_paths = query_bundle_paths_by_suffixes(
                _DISMISSED_BUNDLES_DIR,
                suffixes,
                latest_only=True,
            )
        except (OSError, ValueError):
            indexed_paths = None

        if indexed_paths:
            bundle_paths.extend(path for path in indexed_paths if path.is_file())
        else:
            bundle_paths.extend(_bundle_paths_for_suffixes(suffixes))
    else:
        bundle_paths.extend(_iter_bundle_paths())

    if not bundle_paths:
        return []

    from .tui.models._loaders._json_cache import get_loader_executor

    executor = get_loader_executor()
    results = executor.map(_load_bundle_file, bundle_paths)
    return [a for a in results if a is not None]


def _load_bundle_file(filepath: Path) -> Agent | None:
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


def remove_bundle_by_identity(
    identity: tuple[Any, str, str | None],
    child_raw_suffixes: set[str] | None = None,
) -> bool:
    """Remove bundle file(s) for an agent and optionally its children.

    Args:
        identity: The (AgentType, cl_name, raw_suffix) identity tuple.
        child_raw_suffixes: Raw suffixes of child agents to also remove.

    Returns:
        True if any files were removed, False otherwise.
    """
    removed = False
    _, _, raw_suffix = identity

    def _unlink(path: Path) -> bool:
        try:
            path.unlink()
            if path.name == "bundle.json" and path.parent.name.count(".") >= 1:
                try:
                    path.parent.rmdir()
                except OSError:
                    pass
            return True
        except OSError:
            return False

    def _remove_for_suffix(suffix: str) -> bool:
        changed = False
        for path in _bundle_paths_for_suffixes({suffix}):
            if _unlink(path):
                changed = True
        return changed

    if raw_suffix is not None and _remove_for_suffix(raw_suffix):
        removed = True

    removed_suffixes: set[str] = set()
    if raw_suffix is not None:
        removed_suffixes.add(raw_suffix)

    if child_raw_suffixes:
        for child_suffix in child_raw_suffixes:
            if _remove_for_suffix(child_suffix):
                removed = True
            removed_suffixes.add(child_suffix)

    if removed_suffixes:
        try:
            from .dismissed_bundle_index import delete_bundle_summaries_for_suffixes

            delete_bundle_summaries_for_suffixes(
                _DISMISSED_BUNDLES_DIR, removed_suffixes
            )
        except (OSError, ValueError):
            pass

    return removed


def _maybe_migrate_bundles() -> None:
    """One-time migration from monolithic bundles file to per-agent files.

    If the old ``dismissed_agent_bundles.json`` exists, each entry is written
    as an individual file under ``~/.sase/dismissed_bundles/`` and the
    monolithic file is deleted.  Idempotent — skips duplicates.
    """
    if not _OLD_BUNDLES_FILE.exists():
        return

    from .tui.models.agent import Agent

    try:
        with open(_OLD_BUNDLES_FILE) as f:
            data = json.load(f)
        if not isinstance(data, list):
            _OLD_BUNDLES_FILE.unlink()
            return

        _DISMISSED_BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                agent = Agent.from_bundle_dict(entry)
                save_dismissed_bundle(agent)
            except (KeyError, ValueError, TypeError):
                continue

        _OLD_BUNDLES_FILE.unlink()
    except (OSError, json.JSONDecodeError):
        pass


_ROOT_SHARD_MARKER_NAME = ".root_bundles_sharded"
_CHILD_COLLISION_MARKER_NAME = ".child_collision_fixed"


def _run_dismissed_archive_maintenance() -> None:
    """Run startup-safe, one-shot dismissed archive migrations."""
    _maybe_migrate_bundles()
    _maybe_shard_root_bundles()
    _maybe_fix_child_collisions()


def _maybe_shard_root_bundles() -> None:
    """One-time migration: move pre-shard root bundle files into YYYYMM dirs."""
    marker = _DISMISSED_BUNDLES_DIR / _ROOT_SHARD_MARKER_NAME
    if marker.exists():
        return
    if not _DISMISSED_BUNDLES_DIR.is_dir():
        return

    try:
        for filepath in list(_DISMISSED_BUNDLES_DIR.glob("*.json")):
            if not filepath.is_file():
                continue
            destination = _bundle_shard_dir(filepath.name) / filepath.name
            if destination == filepath:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                filepath.rename(destination)
        marker.touch()
    except OSError:
        pass


def _maybe_fix_child_collisions() -> None:
    """One-time migration: rename child bundles that overwrote their parent.

    Before the ``__c{step_index}`` naming convention, parent and child
    agents both wrote to ``{raw_suffix}.json``, so children silently
    overwrote the parent file.  This scans for those mis-named child
    bundles and renames them to ``{raw_suffix}__c{step_index}.json``.
    """
    marker = _DISMISSED_BUNDLES_DIR / _CHILD_COLLISION_MARKER_NAME
    if marker.exists():
        return
    if not _DISMISSED_BUNDLES_DIR.is_dir():
        return

    try:
        for filepath in list(_iter_bundle_paths()):
            # Skip files already using the child naming convention
            if filepath.name == "bundle.json" or "__c" in filepath.stem:
                continue
            agent = _load_bundle_file(filepath)
            if agent is None:
                continue
            if agent.is_workflow_child:
                new_name = _bundle_filename(agent)
                # Preserve the file's existing shard (its parent directory).
                new_path = filepath.parent / new_name
                if not new_path.exists():
                    filepath.rename(new_path)
    except OSError:
        pass

    # Mark migration complete (even on partial failure — re-running
    # won't help if the OS is failing on us).
    try:
        _DISMISSED_BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass
