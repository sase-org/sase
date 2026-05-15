"""Title formatting for the ACE TUI app."""

from __future__ import annotations

import os

import pytest

from sase.ace.tui.app import AceApp


def test_app_title_includes_pid() -> None:
    app = AceApp(query="!!!", auto_start_axe=False)

    assert app.title == f"sase ace (PID: {os.getpid()})"
    assert app.title.startswith("sase ace ")
    assert app.title.endswith(")")


def test_app_default_initial_tab_is_agents() -> None:
    app = AceApp(query="!!!", auto_start_axe=False)

    assert app.current_tab == "agents"


@pytest.mark.parametrize("tab", ["changespecs", "agents", "axe"])
def test_app_initial_tab_assigned_during_init(tab: str) -> None:
    app = AceApp(query="!!!", auto_start_axe=False, initial_tab=tab)  # type: ignore[arg-type]

    assert app.current_tab == tab
