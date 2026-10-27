"""Local machine identity for non-TUI callers.

The TUI Machines pane used to own this label. Capacity reports and other
core readers need it without importing ACE, so the lookup lives here.
"""

from __future__ import annotations

import platform


def local_machine_label() -> str:
    """Return this host's configured machine name, else the OS node name."""
    try:
        from sase.config import get_local_machine_name

        name = get_local_machine_name()
        if isinstance(name, str) and name.strip():
            return name
    except Exception:
        pass
    return platform.node() or "local"


__all__ = [
    "local_machine_label",
]
