"""Storage for the last-used Agents-tab grouping mode."""

from pathlib import Path

from .tui.models.agent_groups import GroupingMode

_GROUPING_MODE_FILE = Path.home() / ".sase" / "grouping_mode.txt"
_DEFAULT = GroupingMode.STANDARD


def load_grouping_mode() -> GroupingMode:
    """Load the persisted grouping mode, or STANDARD if missing/corrupt."""
    if not _GROUPING_MODE_FILE.exists():
        return _DEFAULT
    try:
        raw = _GROUPING_MODE_FILE.read_text().strip()
    except OSError:
        return _DEFAULT
    try:
        return GroupingMode(raw)
    except ValueError:
        return _DEFAULT


def save_grouping_mode(mode: GroupingMode) -> bool:
    """Persist *mode* to disk. Returns True on success."""
    try:
        _GROUPING_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GROUPING_MODE_FILE.write_text(mode.value)
        return True
    except OSError:
        return False
