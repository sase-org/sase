"""Persistent tracking of dismissed agents across sessions."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .dismissed_agents_bundles import (
    bundle_filename as _bundle_filename_impl,
    bundle_paths_for_suffixes as _bundle_paths_for_suffixes_impl,
    ensure_dismissed_archive_ready as _ensure_dismissed_archive_ready_impl,
    fsync_dir as _fsync_dir_impl,
    has_dismissed_bundle as _has_dismissed_bundle_impl,
    load_bundle_file as _load_bundle_file_impl,
    load_dismissed_bundle_summaries as _load_dismissed_bundle_summaries_impl,
    load_dismissed_bundles as _load_dismissed_bundles_impl,
    mark_bundles_revived_by_suffixes as _mark_bundles_revived_by_suffixes_impl,
    rebuild_dismissed_bundle_index as _rebuild_dismissed_bundle_index_impl,
    save_dismissed_bundle as _save_dismissed_bundle_impl,
    save_dismissed_bundle_python as _save_dismissed_bundle_python_impl,
    verify_dismissed_bundle_index as _verify_dismissed_bundle_index_impl,
    write_json_file_atomic as _write_json_file_atomic_impl,
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
    from .tui.models.agent import Agent, AgentType

_DISMISSED_AGENTS_FILE = Path.home() / ".sase" / "dismissed_agents.json"
_DISMISSED_BUNDLES_DIR = Path.home() / ".sase" / "dismissed_bundles"
_OLD_BUNDLES_FILE = Path.home() / ".sase" / "dismissed_agent_bundles.json"


def _ctx() -> Any:
    return sys.modules[__name__]


def _bundle_shard_dir(filename: str) -> Path:
    return _bundle_shard_dir_impl(_DISMISSED_BUNDLES_DIR, filename)


def _iter_bundle_paths(pattern: str = "*.json") -> list[Path]:
    return _iter_bundle_paths_impl(_DISMISSED_BUNDLES_DIR, pattern)


def _find_bundle(filename: str) -> Path | None:
    return _find_bundle_impl(_DISMISSED_BUNDLES_DIR, filename)


def has_dismissed_bundle(raw_suffix: str) -> bool:
    return _has_dismissed_bundle_impl(_ctx(), raw_suffix)


def load_dismissed_agents() -> set[tuple[AgentType, str, str | None]]:
    return _load_dismissed_agents_impl(_DISMISSED_AGENTS_FILE)


def save_dismissed_agents(
    dismissed: set[tuple[AgentType, str, str | None]],
) -> bool:
    return _save_dismissed_agents_impl(_DISMISSED_AGENTS_FILE, dismissed)


def save_dismissed_bundle(agent: Agent) -> bool:
    return _save_dismissed_bundle_impl(_ctx(), agent)


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
) -> list[Any]:
    return _load_dismissed_bundle_summaries_impl(
        _ctx(),
        suffixes=suffixes,
        cl_name=cl_name,
        project_name=project_name,
        top_level_only=top_level_only,
        limit=limit,
    )


def ensure_dismissed_archive_ready() -> None:
    return _ensure_dismissed_archive_ready_impl(_ctx())


def mark_bundles_revived_by_suffixes(
    suffixes: set[str],
    *,
    revived_at: str | None = None,
) -> int:
    return _mark_bundles_revived_by_suffixes_impl(
        _ctx(), suffixes, revived_at=revived_at
    )


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
    _run_dismissed_archive_maintenance,
    _save_dismissed_bundle_python,
    _write_json_file_atomic,
)
