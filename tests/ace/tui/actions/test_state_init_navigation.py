"""Tests for navigation state initialized before the TUI mounts."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions._state_init_navigation import init_navigation_state


def test_init_navigation_state_initializes_patch_hidden_counts() -> None:
    app = SimpleNamespace()

    init_navigation_state(app)

    assert app._hidden_reverted_count == 0
    assert app._hidden_submitted_count == 0
