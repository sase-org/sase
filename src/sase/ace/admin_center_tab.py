"""Persist the last-focused SASE Admin Center tab across TUI restarts.

This is TUI presentation state — which Admin Center tab ``#`` reopens on — not
shared domain behavior, so it lives in the Python ACE layer rather than the
Rust core. The persisted schema is intentionally tiny: a single tab string
stored under a version-friendly JSON shape (``{"active_tab": "logs"}``).

The valid tab set is *not* duplicated here; callers pass it in (the Admin
Center's ``_TAB_ORDER`` is the single source of truth) so adding a future tab
only requires updating that order, not this module.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path

from sase.core.paths import sase_home

# Test override for the backing file, matching ``_LAST_SELECTION_FILE`` and
# friends. ``None`` falls back to the per-user path under ``sase_home()``.
_ADMIN_CENTER_TAB_FILE: Path | None = None


def _admin_center_tab_file() -> Path:
    return _ADMIN_CENTER_TAB_FILE or sase_home() / "admin_center_tab.json"


def load_admin_center_tab(valid_tabs: Collection[str]) -> str | None:
    """Load the persisted Admin Center tab, validated against *valid_tabs*.

    Returns ``None`` when the file is missing, unreadable, malformed, or holds
    a tab no longer present in *valid_tabs* (e.g. a renamed or removed tab).
    Callers fall back to their own default (``"config"``) on ``None``.
    """
    path = _admin_center_tab_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tab = data.get("active_tab")
    if tab == "telemetry":
        tab = "statistics"
    if not isinstance(tab, str) or tab not in valid_tabs:
        return None
    return tab


def save_admin_center_tab(tab: str, valid_tabs: Collection[str]) -> bool:
    """Persist *tab* as the active Admin Center tab, best-effort.

    Unknown tabs are rejected up front without touching the existing file, so
    a bogus value can never corrupt the stored preference. Returns ``True`` on
    a successful write and ``False`` on rejection or any I/O error; callers
    must never surface a failure to the user.
    """
    if tab not in valid_tabs:
        return False
    try:
        path = _admin_center_tab_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"active_tab": tab}))
        return True
    except OSError:
        return False
