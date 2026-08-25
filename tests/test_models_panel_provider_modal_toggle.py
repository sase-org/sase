"""Models-panel provider-routing modal enable/disable toggle tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel_provider_modal_workers as provider_modal_workers
from sase.ace.tui.modals.models_panel_duration import (
    OverrideUntilCleared,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._models_panel_provider_routing_helpers import (
    disable as _disable,
    snapshot as _snapshot,
    status as _status,
)


async def test_provider_modal_idempotent_disable_does_not_emit_change(
    monkeypatch,
) -> None:
    before_disable = _disable("claude", expires_at=None)
    after_disable = TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider="claude",
        created_at=200.0,
        expires_at=None,
        source="test",
    )
    before = _snapshot(
        _status("claude", active_disable=before_disable),
        disables={"claude": before_disable},
    )
    after = _snapshot(
        _status("claude", active_disable=after_disable),
        disables={"claude": after_disable},
    )
    disable_mock = MagicMock(return_value=after_disable)
    on_snapshot = MagicMock()
    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: after,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(OverrideUntilCleared())
        await wait_for(
            pilot,
            lambda: modal._write_worker is None and disable_mock.called,
        )

    assert modal._changed is False
    on_snapshot.assert_not_called()
    modal.notify.assert_any_call(
        "CLAUDE already has that provider disable.",
        severity="warning",
    )


async def test_provider_modal_disable_replacement_with_new_expiry_emits_change(
    monkeypatch,
) -> None:
    before_disable = _disable("claude", expires_at=None)
    after_disable = _disable("claude", expires_at=4_000.0)
    before = _snapshot(
        _status("claude", active_disable=before_disable),
        disables={"claude": before_disable},
    )
    after = _snapshot(
        _status("claude", active_disable=after_disable),
        disables={"claude": after_disable},
    )
    on_snapshot = MagicMock()
    disable_mock = MagicMock(return_value=after_disable)
    monkeypatch.setattr(
        provider_modal_workers,
        "disable_provider",
        disable_mock,
    )

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=load_snapshot,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(RelativeOverrideDuration(3_900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    assert modal._changed is True
    on_snapshot.assert_called_once()


async def test_provider_modal_enable_writes_and_refreshes_snapshot(monkeypatch) -> None:
    disable = _disable("claude", expires_at=None)
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    after = _snapshot(_status("claude"), disables={})
    enable_mock = MagicMock(return_value=True)
    on_snapshot = MagicMock()
    monkeypatch.setattr(provider_modal_workers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: after,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._submit_enable("claude")
        await wait_for(pilot, lambda: modal._write_worker is None)

    enable_mock.assert_called_once_with("claude")
    assert modal._changed is True
    on_snapshot.assert_called_once()
    modal.notify.assert_any_call("CLAUDE enabled for new launches.")


async def test_provider_modal_enabled_provider_enable_is_noop(monkeypatch) -> None:
    before = _snapshot(_status("claude"))
    enable_mock = MagicMock()
    monkeypatch.setattr(provider_modal_workers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal.action_enable()
        await pilot.pause()

    enable_mock.assert_not_called()
    assert modal._changed is False
    modal.notify.assert_called_once_with(
        "CLAUDE is already enabled.",
        severity="warning",
    )


async def test_provider_modal_idempotent_enable_does_not_emit_change(
    monkeypatch,
) -> None:
    disable = _disable("claude", expires_at=None)
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    enable_mock = MagicMock(return_value=False)
    on_snapshot = MagicMock()
    monkeypatch.setattr(provider_modal_workers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: before,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._submit_enable("claude")
        await wait_for(pilot, lambda: modal._write_worker is None)

    assert modal._changed is False
    on_snapshot.assert_not_called()
    modal.notify.assert_any_call(
        "CLAUDE is already enabled.",
        severity="warning",
    )


async def test_provider_modal_write_failure_reports_error(monkeypatch) -> None:
    before = _snapshot(_status("claude"))
    on_snapshot = MagicMock()

    def fail_disable(*_args, **_kwargs):
        raise RuntimeError("provider store busy")

    monkeypatch.setattr(provider_modal_workers, "disable_provider", fail_disable)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: before,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    assert modal._changed is False
    on_snapshot.assert_not_called()
    modal.notify.assert_any_call(
        "Could not update provider routing: provider store busy",
        severity="error",
    )
