"""Storage for the last selected Patch."""

from pathlib import Path

from sase.core.paths import sase_home

_LAST_SELECTION_FILE: Path | None = None


def _last_selection_file() -> Path:
    return _LAST_SELECTION_FILE or sase_home() / "last_selection.txt"


def load_last_selection() -> str | None:
    """Load the last selected Patch name from disk."""
    path = _last_selection_file()
    if not path.exists():
        return None
    try:
        content = path.read_text().strip()
        return content or None
    except OSError:
        return None


def save_last_selection(name: str) -> bool:
    """Save the currently selected Patch name."""
    try:
        path = _last_selection_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
        return True
    except OSError:
        return False
