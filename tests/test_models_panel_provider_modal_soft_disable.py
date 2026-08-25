"""Models-panel provider-routing modal soft-disable flow tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from textual.widgets import Static

import sase.ace.tui.modals.models_panel_provider_modal as provider_modal
import sase.ace.tui.modals.models_panel_provider_modal_workers as provider_modal_workers
from sase.ace.tui.modals.models_panel_duration import (
    DurationPickerModal,
    KeepCurrentWindow,
)
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
)
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._models_panel_provider_routing_helpers import (
    disable as _disable,
    snapshot as _snapshot,
    status as _status,
)


async def test_provider_modal_s_writes_soft_disable_with_picked_duration(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, mode=PROVIDER_DISABLE_MODE_SOFT)
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DurationPickerModal)
        title = pilot.app.screen.query_one("#provider-duration-title", Static)
        assert title.content == "Soft-disable CLAUDE"
        keys = [choice.key for choice in pilot.app.screen._choices]
        assert "x" not in keys

        await pilot.press("4")
        await wait_for(pilot, lambda: modal._changed)

    disable_mock.assert_called_once_with(
        "claude",
        2 * 60 * 60.0,
        source="ace",
        mode=PROVIDER_DISABLE_MODE_SOFT,
        now=100.0,
    )
    modal.notify.assert_any_call(
        "CLAUDE soft-disabled for 2h; alias routing refreshed."
    )


async def test_provider_modal_d_on_soft_row_offers_keep_current_window(
    monkeypatch,
) -> None:
    disable = _disable(
        "claude",
        expires_at=6_220.0,
        mode=PROVIDER_DISABLE_MODE_SOFT,
    )
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    flipped = _disable("claude", expires_at=6_220.0)
    after = _snapshot(
        _status("claude", active_disable=flipped),
        disables={"claude": flipped},
    )
    exact_disable = MagicMock(return_value=flipped)

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if exact_disable.called else before

    monkeypatch.setattr(provider_modal_workers, "disable_provider_until", exact_disable)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()
        picker = pilot.app.screen
        assert isinstance(picker, DurationPickerModal)
        assert picker._choices[0].key == "x"
        assert isinstance(picker._choices[0].value, KeepCurrentWindow)
        assert picker._choices[0].value.expires_at == 6_220.0
        assert "Keep current window" in picker._choices[0].title

        await pilot.press("x")
        await wait_for(pilot, lambda: modal._changed)

    exact_disable.assert_called_once_with(
        "claude",
        6_220.0,
        source="ace",
        mode=PROVIDER_DISABLE_MODE_HARD,
        now=100.0,
    )
    modal.notify.assert_any_call(
        "CLAUDE disabled with its current window (was soft); alias routing refreshed."
    )


async def test_provider_modal_s_on_soft_row_does_not_offer_keep_current() -> None:
    disable = _disable("claude", expires_at=6_220.0, mode=PROVIDER_DISABLE_MODE_SOFT)
    snapshot = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        picker = pilot.app.screen
        assert isinstance(picker, DurationPickerModal)
        assert [choice.key for choice in picker._choices][0] == "1"
        assert "x" not in [choice.key for choice in picker._choices]


async def test_provider_modal_x_clears_soft_disable(monkeypatch) -> None:
    disable = _disable("claude", expires_at=None, mode=PROVIDER_DISABLE_MODE_SOFT)
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    after = _snapshot(_status("claude"), disables={})
    enable_mock = MagicMock(return_value=True)
    monkeypatch.setattr(provider_modal_workers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: after)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._submit_enable("claude")
        await wait_for(pilot, lambda: modal._write_worker is None)

    enable_mock.assert_called_once_with("claude")
    assert modal._changed is True
    modal.notify.assert_any_call("CLAUDE enabled for new launches.")
