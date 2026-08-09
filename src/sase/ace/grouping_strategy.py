"""Persistence helpers for ACE TUI grouping strategies."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from sase.core.paths import sase_home

from .tui.models.agent_groups import GroupingMode
from .tui.models.patch_groups import PatchGroupingMode

AGENT_GROUPING_MODE_FILENAME = "grouping_mode.txt"
PATCH_GROUPING_MODE_FILENAME = "patch_grouping_mode.txt"
LEGACY_CHANGESPEC_GROUPING_MODE_FILENAME = (  # legacy compatibility filename
    "changespec_grouping_mode.txt"
)

# Compatibility alias for tests and callers that have not migrated yet.
ChangeSpecGroupingMode = PatchGroupingMode  # legacy compatibility alias


def _sase_dir() -> Path:
    return sase_home()


def _agent_grouping_mode_path() -> Path:
    return _sase_dir() / AGENT_GROUPING_MODE_FILENAME


def _patch_grouping_mode_path() -> Path:
    return _sase_dir() / PATCH_GROUPING_MODE_FILENAME


def _legacy_changespec_grouping_mode_path() -> Path:  # legacy compatibility alias
    return _sase_dir() / LEGACY_CHANGESPEC_GROUPING_MODE_FILENAME


def _load_mode[ModeT: Enum](
    path: Path, enum_type: type[ModeT], default: ModeT
) -> ModeT:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return default
    try:
        return enum_type(raw)
    except ValueError:
        return default


def _load_mode_from_paths[ModeT: Enum](
    paths: tuple[Path, ...],
    enum_type: type[ModeT],
    default: ModeT,
) -> ModeT:
    for path in paths:
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        try:
            return enum_type(raw)
        except ValueError:
            return default
    return default


def _save_mode(path: Path, mode: Enum) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{mode.value}\n", encoding="utf-8")
    except OSError:
        return False
    return True


def load_agent_grouping_mode(
    default: GroupingMode = GroupingMode.STANDARD,
) -> GroupingMode:
    """Load the last persisted Agents-tab grouping mode."""
    return _load_mode(_agent_grouping_mode_path(), GroupingMode, default)


def save_agent_grouping_mode(mode: GroupingMode) -> bool:
    """Persist the Agents-tab grouping mode."""
    return _save_mode(_agent_grouping_mode_path(), mode)


def load_patch_grouping_mode(
    default: PatchGroupingMode = PatchGroupingMode.BY_PROJECT,
) -> PatchGroupingMode:
    """Load the last persisted Patch grouping mode."""
    return _load_mode_from_paths(
        (_patch_grouping_mode_path(), _legacy_changespec_grouping_mode_path()),
        PatchGroupingMode,
        default,
    )


def save_patch_grouping_mode(mode: PatchGroupingMode) -> bool:
    """Persist the Patch grouping mode to the canonical filename."""
    return _save_mode(_patch_grouping_mode_path(), mode)


load_changespec_grouping_mode = (  # legacy compatibility alias
    load_patch_grouping_mode
)


def save_changespec_grouping_mode(  # legacy compatibility alias
    mode: PatchGroupingMode,
) -> bool:
    """Persist the legacy ChangeSpec grouping mode filename."""
    return _save_mode(_legacy_changespec_grouping_mode_path(), mode)
