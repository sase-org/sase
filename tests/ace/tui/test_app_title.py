"""Title formatting for the ACE TUI app."""

from __future__ import annotations

import os

from sase.ace.tui.app import AceApp


def test_app_title_includes_pid() -> None:
    app = AceApp(query="!!!", auto_start_axe=False)

    assert app.title == f"sase ace (PID: {os.getpid()})"
    assert app.title.startswith("sase ace ")
    assert app.title.endswith(")")
