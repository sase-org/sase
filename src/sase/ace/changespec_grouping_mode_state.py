"""Storage for the last-used CLs-tab grouping mode.

Kept separate from ``grouping_mode_state`` (which serves the Agents tab)
so cycling on one tab does not perturb the other tab's saved mode.
"""

from pathlib import Path

from .tui.models.changespec_groups import ChangeSpecGroupingMode

_GROUPING_MODE_FILE = Path.home() / ".sase" / "changespec_grouping_mode.txt"
_DEFAULT = ChangeSpecGroupingMode.BY_PROJECT


def load_changespec_grouping_mode() -> ChangeSpecGroupingMode:
    """Load the persisted CL grouping mode, or BY_PROJECT if missing/corrupt."""
    if not _GROUPING_MODE_FILE.exists():
        return _DEFAULT
    try:
        raw = _GROUPING_MODE_FILE.read_text().strip()
    except OSError:
        return _DEFAULT
    try:
        return ChangeSpecGroupingMode(raw)
    except ValueError:
        return _DEFAULT


def save_changespec_grouping_mode(mode: ChangeSpecGroupingMode) -> bool:
    """Persist *mode* to disk. Returns True on success."""
    try:
        _GROUPING_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GROUPING_MODE_FILE.write_text(mode.value)
        return True
    except OSError:
        return False
