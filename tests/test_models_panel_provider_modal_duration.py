"""Models-panel provider-routing modal duration-picker flow tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.widgets import Static

import sase.ace.tui.modals.models_panel_provider_modal as provider_modal
import sase.ace.tui.modals.models_panel_provider_modal_workers as provider_modal_workers
from sase.ace.tui.modals.duration_choice_modal import DurationChoiceCancelled
from sase.ace.tui.modals.models_panel_duration import (
    OPEN_OVERRIDE_UNTIL,
    DurationPickerModal,
    OverrideUntilCleared,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.ace.tui.modals.models_panel_time import (
    OVERRIDE_UNTIL_BACK,
    OverrideUntilModal,
)
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_MODE_HARD
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._models_panel_provider_routing_helpers import (
    disable as _disable,
    snapshot as _snapshot,
    status as _status,
    until_result as _until_result,
)


async def test_provider_modal_duration_cancel_and_back_paths() -> None:
    snapshot = _snapshot(_status("claude"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"

        modal._on_provider_duration_picked(None)
        await pilot.pause()
        assert pilot.app.screen is modal
        modal._on_provider_duration_picked(DurationChoiceCancelled())
        await pilot.pause()
        assert pilot.app.screen is modal

        modal._on_provider_duration_picked(OPEN_OVERRIDE_UNTIL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, OverrideUntilModal)
        title = pilot.app.screen.query_one("#override-until-title", Static)
        assert title.content == "Disable CLAUDE Until"

        modal._on_provider_until_picked(OVERRIDE_UNTIL_BACK)
        await pilot.pause()
        assert isinstance(pilot.app.screen, DurationPickerModal)
        title = pilot.app.screen.query_one("#provider-duration-title", Static)
        assert title.content == "Disable CLAUDE"


@pytest.mark.parametrize(
    ("result", "expected_seconds", "expected_until"),
    [
        (RelativeOverrideDuration(30 * 60.0), 30 * 60.0, None),
        (RelativeOverrideDuration(60 * 60.0), 60 * 60.0, None),
        (RelativeOverrideDuration(2 * 60 * 60.0), 2 * 60 * 60.0, None),
        (RelativeOverrideDuration(4 * 60 * 60.0), 4 * 60 * 60.0, None),
        (RelativeOverrideDuration(45 * 60.0), 45 * 60.0, None),
        (OverrideUntilCleared(), None, None),
        (_until_result(), None, 5_000.0),
    ],
)
async def test_provider_modal_disable_accepts_every_duration_result(
    monkeypatch,
    result,
    expected_seconds,
    expected_until,
) -> None:
    before = _snapshot(_status("claude"))
    expires_at = expected_until
    if expires_at is None and expected_seconds is not None:
        expires_at = 100.0 + expected_seconds
    disable = _disable("claude", expires_at=expires_at)
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    relative_disable = MagicMock(return_value=disable)
    exact_disable = MagicMock(return_value=disable)
    monkeypatch.setattr(provider_modal_workers, "disable_provider", relative_disable)
    monkeypatch.setattr(provider_modal_workers, "disable_provider_until", exact_disable)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if relative_disable.called or exact_disable.called else before

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(result)
        await wait_for(pilot, lambda: modal._write_worker is None)

    if expected_until is None:
        relative_disable.assert_called_once_with(
            "claude",
            expected_seconds,
            source="ace",
            mode=PROVIDER_DISABLE_MODE_HARD,
            now=100.0,
        )
        exact_disable.assert_not_called()
    else:
        exact_disable.assert_called_once_with(
            "claude",
            expected_until,
            source="ace",
            mode=PROVIDER_DISABLE_MODE_HARD,
            now=100.0,
        )
        relative_disable.assert_not_called()
    assert modal._changed is True
    assert modal._snapshot.provider_disables == {"claude": disable}


async def test_provider_modal_disable_writes_and_refreshes_snapshot(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0)
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    load_snapshot_mock = MagicMock(side_effect=load_snapshot)
    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)
    snapshots: list[ProviderRoutingSnapshot] = []

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=load_snapshot_mock,
            on_snapshot=lambda snapshot, _provider: snapshots.append(snapshot),
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("1")
        await wait_for(pilot, lambda: modal._changed)

        disable_mock.assert_called_once_with(
            "claude",
            15 * 60.0,
            source="ace",
            mode=PROVIDER_DISABLE_MODE_HARD,
            now=100.0,
        )
        assert modal._changed is True
        assert snapshots[-1].provider_disables == {"claude": disable}
        modal.notify.assert_any_call(
            "CLAUDE disabled for 15m; alias routing refreshed."
        )
