"""Tests for the Config hub Holds pane: load, render, release."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.holds_pane import HoldsPane
from tests.ace.tui._config_center_tabs_helpers import _HostApp


class _HoldsPaneTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield HoldsPane(id="holds")


def _hold(
    key: str = "agent:hold-a",
    *,
    display: str = "hold-a",
    kind: str = "agent",
    scope_kind: str = "project",
    project: str = "proj",
    names: list[str] | None = None,
    future: bool = False,
    capture: dict[str, int] | None = None,
    expires_at: float | None = 4_102_444_800.0,  # far future by default
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "armer": {"kind": kind, "key": key, "display": display},
        "scope": {"kind": scope_kind, "project": project},
        "selectors": {"names": names or [], "future": future},
        "expires_at": expires_at,
    }
    if capture is not None:
        record["capture"] = capture
    return record


@asynccontextmanager
async def _mounted_pane(monkeypatch: pytest.MonkeyPatch, holds: list[dict[str, Any]]):
    monkeypatch.setattr(HoldsPane, "_list_holds", lambda self: list(holds))
    app = _HoldsPaneTestApp()
    async with app.run_test() as pilot:
        pane = app.query_one("#holds", HoldsPane)
        await wait_for(pilot, lambda: not pane._loading)
        yield pilot, pane


async def test_loads_and_renders_active_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    holds = [
        _hold("agent:hold-a", display="hold-a"),
        _hold(
            "agent:hold-b",
            display="hold-b",
            names=["x"],
            capture={
                "waiting_count": 2,
                "queued_count": 1,
                "skipped_running_count": 3,
            },
        ),
    ]
    async with _mounted_pane(monkeypatch, holds) as (_pilot, pane):
        option_list = pane.query_one("#holds-pane-list", OptionList)
        assert option_list.option_count == 2
        rows = [option_list.get_option_at_index(i).prompt.plain for i in range(2)]
        assert "hold-a" in rows[0]
        assert "capture not recorded" in rows[0]
        assert "hold-b" in rows[1]
        assert "names=x" in rows[1]
        assert "2 waiting + 1 queued; skipped 3 running" in rows[1]
        assert "2 active" in pane._header_text().plain


async def test_empty_state_shows_zero_active_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _mounted_pane(monkeypatch, []) as (_pilot, pane):
        option_list = pane.query_one("#holds-pane-list", OptionList)
        assert option_list.option_count == 0
        assert "0 active" in pane._header_text().plain


async def test_release_highlighted_calls_release_and_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holds = [_hold("agent:hold-a")]
    released: list[str] = []

    def fake_release(self: HoldsPane, armer_key: str) -> None:
        released.append(armer_key)
        holds.clear()

    monkeypatch.setattr(HoldsPane, "_release_hold", fake_release)
    async with _mounted_pane(monkeypatch, holds) as (pilot, pane):
        pane.query_one("#holds-pane-list", OptionList).highlighted = 0
        pane.action_release_highlighted()
        await wait_for(pilot, lambda: not pane._releasing)
        await wait_for(pilot, lambda: len(pane._holds) == 0)
        assert released == ["agent:hold-a"]


async def test_action_close_requests_host_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = []

    class _Host:
        def request_close(self) -> None:
            closed.append(True)

    async with _mounted_pane(monkeypatch, []) as (_pilot, pane):
        pane._host = _Host()
        pane.action_close()
        assert closed == [True]


async def test_holds_subtab_mounts_through_the_config_hub_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(HoldsPane, "_list_holds", lambda self: [_hold("agent:hold-a")])
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="holds"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "holds" in hub._panes)
        pane = hub.query_one("#holds", HoldsPane)
        await wait_for(pilot, lambda: not pane._loading)

        assert hub._active_subtab == "holds"
        assert pane.query_one("#holds-pane-list", OptionList).option_count == 1
