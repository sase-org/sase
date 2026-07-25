"""Shared test doubles for Admin Center tab coverage."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal


class _HostApp(App[None]):
    pass


class _StubPane(Static):
    can_focus = True

    def __init__(self, tab: CenterTab) -> None:
        super().__init__(f"stub {tab}", id=tab)
        self.tab = tab
        self.visibility: list[bool] = []
        self.focus_count = 0
        self.saved_state = ""

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        self.visibility.append(active)

    def focus_default(self) -> None:
        self.focus_count += 1
        self.focus()


class _InputPane(Vertical):
    """Working pane whose filter must retain literal opener characters."""

    def __init__(self, tab: CenterTab) -> None:
        super().__init__(id=tab)

    def compose(self) -> ComposeResult:
        yield Input(id="stub-filter")

    def focus_default(self) -> None:
        self.query_one(Input).focus()


async def _wait_until(
    pilot: Any,
    predicate: Any,
    *,
    timeout: float = 5.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Admin Center test condition timed out")
        await pilot.pause()


def _patch_stub_panes(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[CenterTab, list[_StubPane]], list[CenterTab]]:
    created: dict[CenterTab, list[_StubPane]] = {}
    calls: list[CenterTab] = []

    def create(_self: ConfigCenterModal, tab: CenterTab) -> _StubPane:
        calls.append(tab)
        pane = _StubPane(tab)
        created.setdefault(tab, []).append(pane)
        return pane

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", create)
    return created, calls
