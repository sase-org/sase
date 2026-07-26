"""Persistent tracking of dismissed agents across sessions."""

from __future__ import annotations

import itertools
import sys
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.agent_types import AgentType
from sase.core.paths import sase_home, sase_subdir

from .dismissed_agents_bundles import (
    bundle_filename as _bundle_filename_impl,
    bundle_paths_for_suffixes as _bundle_paths_for_suffixes_impl,
    ensure_dismissed_archive_ready as _ensure_dismissed_archive_ready_impl,
    fsync_dir as _fsync_dir_impl,
    has_dismissed_bundle as _has_dismissed_bundle_impl,
    load_bundle_file as _load_bundle_file_impl,
    load_dismissed_bundle_identities as _load_dismissed_bundle_identities_impl,
    load_dismissed_bundle_summaries as _load_dismissed_bundle_summaries_impl,
    load_dismissed_bundles as _load_dismissed_bundles_impl,
    load_dismissed_bundles_page as _load_dismissed_bundles_page_impl,
    mark_bundles_revived_by_suffixes as _mark_bundles_revived_by_suffixes_impl,
    purge_revived_dismissed_bundles as _purge_revived_dismissed_bundles_impl,
    rebuild_dismissed_bundle_index as _rebuild_dismissed_bundle_index_impl,
    save_dismissed_bundle as _save_dismissed_bundle_impl,
    save_dismissed_bundle_python as _save_dismissed_bundle_python_impl,
    verify_dismissed_bundle_index as _verify_dismissed_bundle_index_impl,
    write_json_file_atomic as _write_json_file_atomic_impl,
)
from .dismissed_agent_groups import (
    delete_dismissed_agent_group as _delete_dismissed_agent_group_impl,
    list_dismissed_agent_groups as _list_dismissed_agent_groups_impl,
    list_recent_dismissed_agent_groups as _list_recent_dismissed_agent_groups_impl,
    load_dismissed_agent_group as _load_dismissed_agent_group_impl,
    load_recent_dismissed_agent_group as _load_recent_dismissed_agent_group_impl,
    mark_dismissed_agent_group_revived as _mark_dismissed_agent_group_revived_impl,
    mark_recent_dismissed_agent_group_revived as _mark_recent_dismissed_agent_group_revived_impl,
    record_recent_dismissed_agent_group as _record_recent_dismissed_agent_group_impl,
    save_dismissed_agent_group as _save_dismissed_agent_group_impl,
)
from .dismissed_agents_migrations import (
    _CHILD_COLLISION_MARKER_NAME,
    _ROOT_SHARD_MARKER_NAME,
    maybe_fix_child_collisions as _maybe_fix_child_collisions_impl,
    maybe_migrate_bundles as _maybe_migrate_bundles_impl,
    maybe_shard_root_bundles as _maybe_shard_root_bundles_impl,
    run_dismissed_archive_maintenance as _run_dismissed_archive_maintenance_impl,
)
from .dismissed_agents_paths import (
    bundle_shard_dir as _bundle_shard_dir_impl,
    find_bundle as _find_bundle_impl,
    iter_bundle_paths as _iter_bundle_paths_impl,
)
from .dismissed_agents_state import (
    load_dismissed_agents as _load_dismissed_agents_impl,
    save_dismissed_agents as _save_dismissed_agents_impl,
)

if TYPE_CHECKING:
    from .tui.models.agent import Agent

_DISMISSED_AGENTS_FILE: Path | None = None
_DISMISSED_BUNDLES_DIR: Path | None = None
_DISMISSED_AGENT_GROUPS_DIR: Path | None = None
_RECENT_DISMISSED_AGENT_GROUPS_DIR: Path | None = None
_OLD_BUNDLES_FILE: Path | None = None


def _ctx() -> Any:
    return sys.modules[__name__]


def _dismissed_agents_file() -> Path:
    return _DISMISSED_AGENTS_FILE or sase_home() / "dismissed_agents.json"


def dismissed_bundles_dir() -> Path:
    return _DISMISSED_BUNDLES_DIR or sase_subdir("dismissed_bundles")


def dismissed_agent_groups_dir() -> Path:
    return _DISMISSED_AGENT_GROUPS_DIR or sase_subdir("dismissed_agent_groups")


def _recent_dismissed_agent_groups_dir() -> Path:
    return _RECENT_DISMISSED_AGENT_GROUPS_DIR or sase_subdir(
        "recent_dismissed_agent_groups"
    )


def _old_bundles_file() -> Path:
    return _OLD_BUNDLES_FILE or sase_home() / "dismissed_agent_bundles.json"


def _bundle_shard_dir(filename: str) -> Path:
    return _bundle_shard_dir_impl(dismissed_bundles_dir(), filename)


def _iter_bundle_paths(pattern: str = "*.json") -> list[Path]:
    return _iter_bundle_paths_impl(dismissed_bundles_dir(), pattern)


def _find_bundle(filename: str) -> Path | None:
    return _find_bundle_impl(dismissed_bundles_dir(), filename)


def has_dismissed_bundle(raw_suffix: str) -> bool:
    return _has_dismissed_bundle_impl(_ctx(), raw_suffix)


def load_dismissed_agents() -> set[tuple[AgentType, str, str | None]]:
    return _load_dismissed_agents_impl(_dismissed_agents_file())


def dismissed_agents_file_signature() -> tuple[int, int] | None:
    try:
        stat = _dismissed_agents_file().stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def dismissed_bundle_index_signature() -> tuple[int, int, int, int] | None:
    try:
        from .dismissed_bundle_index import index_signature
    except (ImportError, AttributeError):
        return None
    return index_signature(dismissed_bundles_dir())


_DISMISSED_BUNDLE_IDENTITIES_SNAPSHOT_LOCK = threading.Lock()
_dismissed_bundle_identities_snapshot_initialized = False
_dismissed_bundle_identities_snapshot_signature: tuple[int, int, int, int] | None = None
_dismissed_bundle_identities_snapshot_cache: frozenset[
    tuple[AgentType, str, str | None]
] = frozenset()


def dismissed_bundle_identities_snapshot() -> set[tuple[AgentType, str, str | None]]:
    """Return bundle-index identities, re-querying only when its signature changes."""
    global _dismissed_bundle_identities_snapshot_cache
    global _dismissed_bundle_identities_snapshot_initialized
    global _dismissed_bundle_identities_snapshot_signature

    from .dismissed_bundle_index import query_summary_identities

    with _DISMISSED_BUNDLE_IDENTITIES_SNAPSHOT_LOCK:
        signature = dismissed_bundle_index_signature()
        if (
            _dismissed_bundle_identities_snapshot_initialized
            and signature == _dismissed_bundle_identities_snapshot_signature
        ):
            return set(_dismissed_bundle_identities_snapshot_cache)

        queried = query_summary_identities(dismissed_bundles_dir())
        if queried is None:
            # A missing/unusable index has no authoritative bundle projection.
            # Do not retain an old snapshot after its signature disappears.
            identities: set[tuple[AgentType, str, str | None]] = set()
        else:
            identities = {
                (AgentType(agent_type), cl_name, raw_suffix)
                for agent_type, cl_name, raw_suffix in queried
            }
        _dismissed_bundle_identities_snapshot_cache = frozenset(identities)
        _dismissed_bundle_identities_snapshot_signature = signature
        _dismissed_bundle_identities_snapshot_initialized = True
        return set(_dismissed_bundle_identities_snapshot_cache)


_DISMISSED_SAVE_LOCK = threading.Lock()
_dismissed_snapshot_generations = itertools.count(1)
_last_saved_dismissed_generation: dict[Path, int] = {}


class _DismissedAgentsSnapshot(set):
    """Dismissed-identity snapshot stamped with its capture generation."""

    generation: int = 0


def snapshot_dismissed_agents(
    dismissed: Iterable[tuple[AgentType, str, str | None]],
) -> _DismissedAgentsSnapshot:
    """Copy *dismissed* for handoff to a background persistence worker.

    Capture on the thread that mutates the live set so generation order
    matches mutation order; :func:`save_dismissed_agents` then skips any
    snapshot that a newer snapshot (or live-set save) has already
    persisted, so concurrent persistence workers cannot overwrite newer
    state with an older full-set snapshot.
    """
    snapshot = _DismissedAgentsSnapshot(dismissed)
    with _DISMISSED_SAVE_LOCK:
        snapshot.generation = next(_dismissed_snapshot_generations)
    return snapshot


def save_dismissed_agents(
    dismissed: set[tuple[AgentType, str, str | None]],
) -> bool:
    """Save the dismissed set, skipping snapshots a newer save supersedes.

    Returns False when the write failed or when *dismissed* is a
    generation-stamped snapshot that an equal-or-newer generation has
    already persisted for the same file; callers gate the artifact-index
    sync on this result, so a superseded snapshot never reaches disk or
    the index.
    """
    global _last_saved_dismissed_generation
    target = _dismissed_agents_file()
    with _DISMISSED_SAVE_LOCK:
        generation = getattr(dismissed, "generation", 0)
        if generation:
            if generation <= _last_saved_dismissed_generation.get(target, 0):
                return False
        else:
            # An unstamped save passes the live set from the owning thread,
            # which reflects every previously captured snapshot's mutations.
            generation = next(_dismissed_snapshot_generations)
        if not _save_dismissed_agents_impl(target, dismissed):
            return False
        _last_saved_dismissed_generation[target] = generation
        return True


def save_dismissed_bundle(agent: Agent) -> bool:
    return _save_dismissed_bundle_impl(_ctx(), agent)


def dismissed_bundle_path_for_agent(agent: Agent) -> Path | None:
    """Return the dismissed bundle path for *agent* when one exists."""
    return _find_bundle(_bundle_filename(agent))


def rebuild_dismissed_bundle_index() -> tuple[int, int]:
    return _rebuild_dismissed_bundle_index_impl(_ctx())


def verify_dismissed_bundle_index() -> dict[str, int | bool]:
    return _verify_dismissed_bundle_index_impl(_ctx())


def load_dismissed_bundle_summaries(
    *,
    suffixes: set[str] | None = None,
    cl_name: str | None = None,
    project_name: str | None = None,
    top_level_only: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Any]:
    return _load_dismissed_bundle_summaries_impl(
        _ctx(),
        suffixes=suffixes,
        cl_name=cl_name,
        project_name=project_name,
        top_level_only=top_level_only,
        limit=limit,
        offset=offset,
    )


def load_dismissed_bundle_identities() -> set[tuple[str, str, str | None]]:
    return _load_dismissed_bundle_identities_impl(_ctx())


def ensure_dismissed_archive_ready() -> None:
    return _ensure_dismissed_archive_ready_impl(_ctx())


def save_dismissed_agent_group(group: Any) -> Any:
    return _save_dismissed_agent_group_impl(
        group, groups_dir=dismissed_agent_groups_dir()
    )


def list_dismissed_agent_groups(
    *,
    limit: int = 20,
    cursor: int | None = None,
) -> Any:
    return _list_dismissed_agent_groups_impl(
        limit=limit, cursor=cursor, groups_dir=dismissed_agent_groups_dir()
    )


def load_dismissed_agent_group(group_id: str) -> Any:
    return _load_dismissed_agent_group_impl(
        group_id, groups_dir=dismissed_agent_groups_dir()
    )


def mark_dismissed_agent_group_revived(
    group_id: str,
    *,
    revived_at: str,
) -> Any:
    return _mark_dismissed_agent_group_revived_impl(
        group_id,
        revived_at=revived_at,
        groups_dir=dismissed_agent_groups_dir(),
    )


def delete_dismissed_agent_group(group_id: str) -> bool:
    return _delete_dismissed_agent_group_impl(
        group_id,
        groups_dir=dismissed_agent_groups_dir(),
    )


def record_recent_dismissed_agent_group(group: Any, *, limit: int = 10) -> Any:
    return _record_recent_dismissed_agent_group_impl(
        group,
        groups_dir=_recent_dismissed_agent_groups_dir(),
        limit=limit,
    )


def list_recent_dismissed_agent_groups(*, limit: int = 10) -> Any:
    return _list_recent_dismissed_agent_groups_impl(
        limit=limit,
        groups_dir=_recent_dismissed_agent_groups_dir(),
    )


def load_recent_dismissed_agent_group(group_id: str) -> Any:
    return _load_recent_dismissed_agent_group_impl(
        group_id,
        groups_dir=_recent_dismissed_agent_groups_dir(),
    )


def mark_recent_dismissed_agent_group_revived(
    group_id: str,
    *,
    revived_at: str,
) -> Any:
    return _mark_recent_dismissed_agent_group_revived_impl(
        group_id,
        revived_at=revived_at,
        groups_dir=_recent_dismissed_agent_groups_dir(),
    )


def mark_bundles_revived_by_suffixes(
    suffixes: set[str],
    *,
    revived_at: str | None = None,
) -> int:
    return _mark_bundles_revived_by_suffixes_impl(
        _ctx(), suffixes, revived_at=revived_at
    )


def purge_revived_dismissed_bundles() -> int:
    return _purge_revived_dismissed_bundles_impl(_ctx())


def _bundle_paths_for_suffixes(suffixes: set[str]) -> list[Path]:
    return _bundle_paths_for_suffixes_impl(_ctx(), suffixes)


def _save_dismissed_bundle_python(root: Path, bundle: dict[str, Any]) -> Path:
    return _save_dismissed_bundle_python_impl(root, bundle)


def _write_json_file_atomic(path: Path, data: dict[str, Any]) -> None:
    return _write_json_file_atomic_impl(path, data)


def _fsync_dir(path: Path) -> None:
    return _fsync_dir_impl(path)


def _bundle_filename(agent: Agent) -> str:
    return _bundle_filename_impl(agent)


def load_dismissed_bundles(suffixes: set[str] | None = None) -> list[Agent]:
    return _load_dismissed_bundles_impl(_ctx(), suffixes)


def load_dismissed_bundles_page(
    *,
    cl_name: str | None = None,
    project_name: str | None = None,
    limit: int = 250,
    offset: int = 0,
) -> tuple[list[Agent], bool]:
    return _load_dismissed_bundles_page_impl(
        _ctx(),
        cl_name=cl_name,
        project_name=project_name,
        limit=limit,
        offset=offset,
    )


def _load_bundle_file(filepath: Path) -> Agent | None:
    return _load_bundle_file_impl(filepath)


def _maybe_migrate_bundles() -> None:
    return _maybe_migrate_bundles_impl(_ctx())


def _run_dismissed_archive_maintenance() -> None:
    return _run_dismissed_archive_maintenance_impl(_ctx())


def _maybe_shard_root_bundles() -> None:
    return _maybe_shard_root_bundles_impl(_ctx())


def _maybe_fix_child_collisions() -> None:
    return _maybe_fix_child_collisions_impl(_ctx())


_PRIVATE_COMPAT_EXPORTS = (
    _bundle_filename,
    _bundle_paths_for_suffixes,
    _bundle_shard_dir,
    _find_bundle,
    _fsync_dir,
    _iter_bundle_paths,
    _load_bundle_file,
    _maybe_fix_child_collisions,
    _maybe_migrate_bundles,
    _maybe_shard_root_bundles,
    _old_bundles_file,
    _run_dismissed_archive_maintenance,
    _save_dismissed_bundle_python,
    _write_json_file_atomic,
)
