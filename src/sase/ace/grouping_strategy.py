"""Persistence helpers for ACE TUI grouping strategies."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from .tui.models.agent_groups import GroupingMode
from .tui.models.changespec_groups import ChangeSpecGroupingMode

AGENT_GROUPING_MODE_FILENAME = "grouping_mode.txt"
CHANGESPEC_GROUPING_MODE_FILENAME = "changespec_grouping_mode.txt"


def _sase_dir() -> Path:
    return Path.home() / ".sase"


def _agent_grouping_mode_path() -> Path:
    return _sase_dir() / AGENT_GROUPING_MODE_FILENAME


def _changespec_grouping_mode_path() -> Path:
    return _sase_dir() / CHANGESPEC_GROUPING_MODE_FILENAME


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


def load_changespec_grouping_mode(
    default: ChangeSpecGroupingMode = ChangeSpecGroupingMode.BY_PROJECT,
) -> ChangeSpecGroupingMode:
    """Load the last persisted CLs-tab grouping mode."""
    return _load_mode(
        _changespec_grouping_mode_path(),
        ChangeSpecGroupingMode,
        default,
    )


def save_changespec_grouping_mode(mode: ChangeSpecGroupingMode) -> bool:
    """Persist the CLs-tab grouping mode."""
    return _save_mode(_changespec_grouping_mode_path(), mode)
