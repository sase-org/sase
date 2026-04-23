"""Persistent tracking of dismissed agents across sessions."""

from __future__ import annotations

import json
import re
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
            results.extend(entry.glob(pattern))
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
    try:
        _DISMISSED_AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            [agent_type.value, cl_name, raw_suffix]
            for agent_type, cl_name, raw_suffix in dismissed
        ]
        with open(_DISMISSED_AGENTS_FILE, "w") as f:
            json.dump(entries, f, indent=2)
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
    try:
        filename = _bundle_filename(agent)
        shard_dir = _bundle_shard_dir(filename)
        shard_dir.mkdir(parents=True, exist_ok=True)
        filepath = shard_dir / filename
        with open(filepath, "w") as f:
            json.dump(agent.to_bundle_dict(), f, indent=2)
        return True
    except OSError:
        return False


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
    _maybe_migrate_bundles()
    _maybe_fix_child_collisions()

    if not _DISMISSED_BUNDLES_DIR.is_dir():
        return []

    # Collect the list of bundle files to load, then read them in parallel.
    bundle_paths: list[Path] = []
    if suffixes is not None:
        # Scan across shards (and legacy top-level) → map raw_suffix → list
        # of child filenames.  Raw suffixes are 14-digit timestamps that
        # never contain ``__c``; child filenames always have the form
        # ``{suffix}__c{index}.json``.
        child_files_by_suffix: dict[str, list[Path]] = {}
        try:
            for path in _iter_bundle_paths():
                name = path.name
                stem = name[: -len(".json")]
                marker = stem.find("__c")
                if marker == -1:
                    continue
                raw_suffix = stem[:marker]
                child_files_by_suffix.setdefault(raw_suffix, []).append(path)
        except OSError:
            return []

        for suffix in suffixes:
            parent_path = _find_bundle(f"{suffix}.json")
            if parent_path is not None:
                bundle_paths.append(parent_path)
            bundle_paths.extend(child_files_by_suffix.get(suffix, []))
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
        return Agent.from_bundle_dict(data)
    except (KeyError, ValueError, TypeError):
        return None


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
            return True
        except OSError:
            return False

    def _remove_for_suffix(suffix: str) -> bool:
        changed = False
        parent = _find_bundle(f"{suffix}.json")
        if parent is not None and _unlink(parent):
            changed = True
        # Child bundles live under the same shard as the parent; scan all
        # shards in case of legacy layout mismatches.
        for path in _iter_bundle_paths(pattern=f"{suffix}__c*.json"):
            if _unlink(path):
                changed = True
        return changed

    if raw_suffix is not None and _remove_for_suffix(raw_suffix):
        removed = True

    if child_raw_suffixes:
        for child_suffix in child_raw_suffixes:
            if _remove_for_suffix(child_suffix):
                removed = True

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


_CHILD_COLLISION_MARKER = _DISMISSED_BUNDLES_DIR / ".child_collision_fixed"


def _maybe_fix_child_collisions() -> None:
    """One-time migration: rename child bundles that overwrote their parent.

    Before the ``__c{step_index}`` naming convention, parent and child
    agents both wrote to ``{raw_suffix}.json``, so children silently
    overwrote the parent file.  This scans for those mis-named child
    bundles and renames them to ``{raw_suffix}__c{step_index}.json``.
    """
    if _CHILD_COLLISION_MARKER.exists():
        return
    if not _DISMISSED_BUNDLES_DIR.is_dir():
        return

    try:
        for filepath in list(_iter_bundle_paths()):
            # Skip files already using the child naming convention
            if "__c" in filepath.stem:
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
        _CHILD_COLLISION_MARKER.touch()
    except OSError:
        pass
