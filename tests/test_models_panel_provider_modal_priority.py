"""Models-panel provider-routing modal priority tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel_provider_modal as provider_modal_module
import sase.ace.tui.modals.models_panel_provider_modal_workers as provider_workers
from sase.ace.tui.modals.models_panel_duration import (
    DurationPickerModal,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.llm_provider.provider_priority import (
    PROVIDER_PRIORITY_WRITE_WIRE_SCHEMA_VERSION,
    ProviderPriorityWriteOutcome,
)
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._models_panel_provider_routing_helpers import (
    disable as _disable,
    priority as _priority,
    snapshot as _snapshot,
    status as _status,
)


def _write_outcome(
    status: str,
    *,
    record=None,
    current=None,
    reason: str | None = None,
) -> ProviderPriorityWriteOutcome:
    return ProviderPriorityWriteOutcome(
        version=PROVIDER_PRIORITY_WRITE_WIRE_SCHEMA_VERSION,
        status=status,  # type: ignore[arg-type]
        record=record,
        current=current,
        reason=reason,
    )


async def test_provider_modal_p_opens_priority_duration() -> None:
    before = _snapshot(_status("claude"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_prioritize()
        await pilot.pause()

        assert isinstance(pilot.app.screen, DurationPickerModal)
        assert pilot.app.screen._title == "Prioritize CLAUDE"


async def test_provider_modal_p_on_current_priority_opens_change_duration(
    monkeypatch,
) -> None:
    record = _priority("claude", expires_at=3_820.0)
    before = _snapshot(
        _status("claude", priority=record, provenance=("priority",)),
        provider_priority=record,
    )
    monkeypatch.setattr(provider_modal_module, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_prioritize()
        await pilot.pause()

        assert isinstance(pilot.app.screen, DurationPickerModal)
        assert pilot.app.screen._title == "Change CLAUDE priority"


async def test_provider_modal_p_rejects_disabled_provider(monkeypatch) -> None:
    disable = _disable("claude", expires_at=None)
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    set_mock = MagicMock()
    monkeypatch.setattr(provider_workers, "set_provider_priority", set_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_prioritize()
        await pilot.pause()

    set_mock.assert_not_called()
    modal.notify.assert_called_once_with(
        "Enable CLAUDE with x before prioritizing it.",
        severity="warning",
    )


async def test_provider_modal_sets_priority_and_refreshes(monkeypatch) -> None:
    record = _priority("claude", expires_at=1_000.0)
    before = _snapshot(_status("claude"))
    after = _snapshot(
        _status("claude", priority=record, provenance=("priority",)),
        provider_priority=record,
    )
    set_mock = MagicMock(return_value=_write_outcome("changed", record=record))
    facts_mock = MagicMock(return_value={"provider": "claude"})
    on_snapshot = MagicMock()
    monkeypatch.setattr(provider_workers, "set_provider_priority", set_mock)
    monkeypatch.setattr(provider_workers, "provider_routing_facts", facts_mock)
    monkeypatch.setattr(provider_modal_module, "now", lambda: 100.0)

    def load_snapshot():
        return after if set_mock.called else before

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

        modal._submit_priority(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    set_mock.assert_called_once_with(
        "claude",
        900.0,
        source="ace",
        facts={"provider": "claude"},
        expected=None,
        now=100.0,
    )
    assert modal._changed is True
    on_snapshot.assert_called()
    modal.notify.assert_any_call(
        "CLAUDE priority set for 15m; alias routing refreshed."
    )


async def test_provider_modal_priority_conflict_refreshes_and_requests_retry(
    monkeypatch,
) -> None:
    expected = _priority("codex", expires_at=1_000.0)
    current = _priority("claude", expires_at=2_000.0)
    before = _snapshot(
        _status("codex", priority=expected, provenance=("priority",)),
        provider_priority=expected,
    )
    after = _snapshot(
        _status("claude", priority=current, provenance=("priority",)),
        provider_priority=current,
    )
    set_mock = MagicMock(return_value=_write_outcome("conflict", current=current))
    monkeypatch.setattr(provider_workers, "set_provider_priority", set_mock)
    monkeypatch.setattr(
        provider_workers,
        "provider_routing_facts",
        lambda _provider: {"provider": "codex"},
    )
    monkeypatch.setattr(provider_modal_module, "now", lambda: 100.0)

    def load_snapshot():
        return after if set_mock.called else before

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "codex"

        modal._submit_priority(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    assert modal._snapshot is after
    assert modal._changed is False
    modal.notify.assert_any_call(
        "Provider priority changed in another session; refreshed CLAUDE priority. "
        "Choose p again to replace it.",
        severity="warning",
    )


async def test_provider_modal_clear_priority_without_selectable_rows(
    monkeypatch,
) -> None:
    record = _priority("codex", expires_at=1_000.0)
    before = _snapshot(provider_priority=record)
    after = _snapshot()
    clear_mock = MagicMock(return_value=_write_outcome("changed", record=record))
    monkeypatch.setattr(provider_workers, "clear_provider_priority", clear_mock)
    monkeypatch.setattr(provider_modal_module, "now", lambda: 100.0)

    def load_snapshot():
        return after if clear_mock.called else before

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_clear_priority()
        await wait_for(pilot, lambda: modal._write_worker is None)

    clear_mock.assert_called_once_with(expected=record, now=100.0)
    assert modal._snapshot is after
    assert modal._changed is True
    modal.notify.assert_any_call("CODEX priority cleared; alias routing refreshed.")


async def test_provider_modal_priority_refresh_failure_marks_committed_write(
    monkeypatch,
) -> None:
    record = _priority("claude", expires_at=1_000.0)
    before = _snapshot(_status("claude"))
    set_mock = MagicMock(return_value=_write_outcome("changed", record=record))
    monkeypatch.setattr(provider_workers, "set_provider_priority", set_mock)
    monkeypatch.setattr(
        provider_workers,
        "provider_routing_facts",
        lambda _provider: {"provider": "claude"},
    )
    monkeypatch.setattr(provider_modal_module, "now", lambda: 100.0)

    def load_snapshot():
        if not set_mock.called:
            return before
        raise RuntimeError("routing cache unavailable")

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._snapshot_worker = None
        modal._pending_provider = "claude"

        modal._submit_priority(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    assert modal._changed is True
    modal.notify.assert_any_call(
        "Provider routing was updated, but refresh failed: routing cache unavailable",
        severity="warning",
    )
