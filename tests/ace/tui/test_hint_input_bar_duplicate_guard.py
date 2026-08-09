"""Regression tests for duplicate hint input bar mounting."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input

from sase.ace.tui.actions.hints._files import FileViewingMixin
from sase.ace.tui.actions.hints._processing import InputProcessingMixin
from sase.ace.tui.widgets import HintInputBar


class _DetailWithHints:
    def __init__(self) -> None:
        self.update_calls = 0

    def update_display_with_hints(self, *args: Any, **kwargs: Any) -> tuple[Any, ...]:
        self.update_calls += 1
        return ({1: "/tmp/example.txt"}, {}, {}, {})


class _HintBarDuplicateApp(FileViewingMixin, App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.current_tab = "patches"
        self.current_idx = 0
        self.patches = [SimpleNamespace(name="feature")]
        self.canonical_query_string = ""
        self.hooks_collapsed = None
        self.commits_collapsed = None
        self.mentors_collapsed = None
        self.timestamps_collapsed = None
        self.deltas_collapsed = None
        self._hint_mode_active = False
        self._accept_mode_active = False
        self._rewind_mode_active = False
        self._detail = _DetailWithHints()

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-container"):
            yield Button("Other", id="other")

    def query_one(self, selector: str, expect_type: type[Any] | None = None) -> Any:
        if selector == "#detail-panel":
            return self._detail
        if expect_type is None:
            return super().query_one(selector)
        return super().query_one(selector, expect_type)


class _RemoveHintBarApp(InputProcessingMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self._hint_mode_active = True
        self._hint_mode_hints_for = "hooks_latest_only"
        self._accept_mode_active = True
        self._rewind_mode_active = True
        self.agent_refresh_saw_hint_bar_active: bool | None = None
        self.display_refreshes = 0

    def _refresh_agents_display(self) -> None:
        self.agent_refresh_saw_hint_bar_active = self._hint_input_bar_active()

    def _refresh_display(self) -> None:
        self.display_refreshes += 1


@pytest.mark.asyncio
async def test_view_files_refocuses_existing_hint_bar_instead_of_remounting() -> None:
    app = _HintBarDuplicateApp()

    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()

        app.action_view_files()
        await pilot.pause()

        hint_bar = app.query_one("#hint-input-bar", HintInputBar)
        assert list(app.query(HintInputBar)) == [hint_bar]
        assert app._detail.update_calls == 1

        other = app.query_one("#other", Button)
        other.focus()
        await pilot.pause()
        assert app.focused is other

        app.action_view_files()
        await pilot.pause()

        hint_input = hint_bar.query_one("#hint-input", Input)
        assert list(app.query(HintInputBar)) == [hint_bar]
        assert app.focused is hint_input
        assert app._detail.update_calls == 1


def test_remove_hint_input_bar_opens_focus_gate_before_agents_refresh() -> None:
    app = _RemoveHintBarApp()

    app._remove_hint_input_bar()

    assert app._hint_input_bar_active() is False
    assert app._hint_mode_hints_for is None
    assert app.agent_refresh_saw_hint_bar_active is False
    assert app.display_refreshes == 0
