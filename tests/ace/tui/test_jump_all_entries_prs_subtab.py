"""Regression: jump-all modal Patch jumps land on the Artifacts PRs sub-tab.

``action_jump_to_all_entries`` only lists Patch entries under the
Artifacts tab, so PRs is unconditionally the right pane to land on there.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.navigation._modals import NavigationModalMixin
from sase.ace.tui.modals.jump_all_modal import JumpAllResult


class _FakeApp(NavigationModalMixin):
    """Minimal stand-in exercising the jump-all dismiss handler."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_artifacts_subtab = "stitches"
        self.current_idx = 0
        self.patches: list[Any] = []
        self._agents: list[Any] = []
        self._axe_items: list[Any] = []
        self._jump_all_last_position: JumpAllResult | None = None
        self._on_dismiss: Any = None
        self._save_current_tab_position_calls = 0

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self._on_dismiss = callback

    def _save_current_tab_position(self) -> None:
        self._save_current_tab_position_calls += 1


def test_jump_to_patch_entry_selects_prs_subtab() -> None:
    app = _FakeApp()
    app.action_jump_to_all_entries()
    assert app._on_dismiss is not None

    app._on_dismiss(JumpAllResult(tab="patches", index=2))

    assert app.current_tab == "patches"
    assert app.current_artifacts_subtab == "prs"
    assert app.current_idx == 2


def test_jump_to_agents_entry_leaves_artifacts_subtab_untouched() -> None:
    app = _FakeApp()
    app.action_jump_to_all_entries()
    assert app._on_dismiss is not None

    app._on_dismiss(JumpAllResult(tab="agents", index=1))

    assert app.current_tab == "agents"
    assert app.current_artifacts_subtab == "stitches"
    assert app.current_idx == 1


def test_dismiss_with_none_result_does_nothing() -> None:
    app = _FakeApp()
    app.action_jump_to_all_entries()
    assert app._on_dismiss is not None

    app._on_dismiss(None)

    assert app.current_tab == "agents"
    assert app.current_idx == 0
    assert app._save_current_tab_position_calls == 0
