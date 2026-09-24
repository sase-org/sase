"""Interaction and lifecycle tests for `ProviderUsageModal`."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from textual.widgets import DataTable, OptionList, Static
from textual.worker import WorkerState

import sase.ace.tui.modals.models_panel_usage_modal as usage_modal
from sase.ace.tui.modals.models_panel_usage_modal import ProviderUsageModal
from sase.llm_provider.usage.refresh import (
    UsageRefreshReceipt,
    UsageRefreshProviderResult,
)
from sase.llm_provider.usage.store import ProviderUsageRefreshReservation
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._usage_view_helpers import usage_provider, usage_view_snapshot


def _reservation(
    provider: str, operation_id: str = "op-1"
) -> ProviderUsageRefreshReservation:
    return ProviderUsageRefreshReservation(
        version=1,
        provider=provider,
        context_id="default",
        account_generation=1,
        operation_id=operation_id,
        lease_id=f"lease-{provider}",
        reserved_at=1_800_000_000.0,
        expires_at=1_800_000_100.0,
    )


def _receipt(*, provider: str, operation_id: str, status: str) -> UsageRefreshReceipt:
    result = UsageRefreshProviderResult(
        provider=provider, status=status, reason=None, operation_id=operation_id
    )
    return UsageRefreshReceipt(
        schema_version=1,
        origin="ace",
        operation_ids=(operation_id,),
        providers=(result,),
    )


async def test_usage_modal_first_paint_uses_cached_snapshot() -> None:
    snapshot = usage_view_snapshot(usage_provider("codex"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#provider-usage-list", OptionList)
        assert [str(o.id) for o in option_list.options] == ["codex"]
        footer = modal.query_one("#provider-usage-footer", Static)
        assert "⚠=Collector failing" in footer.render().plain


async def test_usage_modal_loads_in_background_when_no_snapshot_given() -> None:
    snapshot = usage_view_snapshot(usage_provider("grok"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._snapshot is snapshot)

        option_list = modal.query_one("#provider-usage-list", OptionList)
        assert [str(o.id) for o in option_list.options] == ["grok"]


async def test_usage_modal_enter_focuses_detail_table() -> None:
    snapshot = usage_view_snapshot(usage_provider("codex"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        table = modal.query_one("#provider-usage-detail", DataTable)
        assert modal.app.focused is table


async def test_usage_modal_tab_moves_focus_between_list_and_detail() -> None:
    snapshot = usage_view_snapshot(usage_provider("codex"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#provider-usage-list", OptionList)
        table = modal.query_one("#provider-usage-detail", DataTable)
        assert modal.app.focused is option_list

        await pilot.press("tab")
        await pilot.pause()
        assert modal.app.focused is table

        await pilot.press("tab")
        await pilot.pause()
        assert modal.app.focused is not table


async def test_usage_modal_escape_dismisses_immediately_while_update_running() -> None:
    snapshot = usage_view_snapshot(usage_provider("codex"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal._update_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
        modal._pending = {"codex": "op-1"}

        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(pilot.app.screen, ProviderUsageModal)


async def test_usage_modal_update_marks_providers_and_clears_on_completion(
    monkeypatch,
) -> None:
    initial = usage_view_snapshot(usage_provider("codex", collection_status="ok"))
    refreshed = usage_view_snapshot(usage_provider("codex", collection_status="ok"))
    receipt = _receipt(provider="codex", operation_id="op-1", status="reserved")
    monkeypatch.setattr(usage_modal, "submit_usage_refresh", lambda *a, **k: receipt)
    monkeypatch.setattr(
        usage_modal, "list_provider_usage_refresh_reservations", lambda: ()
    )
    calls = {"n": 0}

    def load_snapshot() -> object:
        calls["n"] += 1
        return initial if calls["n"] == 1 else refreshed

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(initial, load_snapshot=load_snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_update_usage()
        await wait_for(pilot, lambda: modal._pending == {"codex": "op-1"})

        option_list = modal.query_one("#provider-usage-list", OptionList)
        assert "Updating" in option_list.get_option_at_index(0).prompt.plain

        await wait_for(pilot, lambda: not modal._pending, timeout=5.0)
        await wait_for(pilot, lambda: modal._snapshot is refreshed, timeout=5.0)

        option_list = modal.query_one("#provider-usage-list", OptionList)
        assert "Updating" not in option_list.get_option_at_index(0).prompt.plain


async def test_usage_modal_failed_reservation_read_keeps_tracking(
    monkeypatch,
) -> None:
    initial = usage_view_snapshot(usage_provider("codex", collection_status="ok"))
    refreshed = usage_view_snapshot(usage_provider("codex", collection_status="ok"))
    receipt = _receipt(provider="codex", operation_id="op-1", status="reserved")
    monkeypatch.setattr(usage_modal, "submit_usage_refresh", lambda *a, **k: receipt)
    reads = {"n": 0}

    def flaky_reservations():
        reads["n"] += 1
        if reads["n"] <= 2:
            raise RuntimeError("store unreadable")
        return ()

    monkeypatch.setattr(
        usage_modal, "list_provider_usage_refresh_reservations", flaky_reservations
    )
    calls = {"n": 0}

    def load_snapshot() -> object:
        calls["n"] += 1
        return initial if calls["n"] == 1 else refreshed

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(initial, load_snapshot=load_snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_update_usage()
        await wait_for(pilot, lambda: modal._pending == {"codex": "op-1"})

        # Two failed polls must leave tracking alone: no early finish, and
        # no snapshot reload behind the spinner.
        await wait_for(pilot, lambda: reads["n"] >= 2, timeout=5.0)
        await pilot.pause()
        await pilot.pause()
        assert modal._pending == {"codex": "op-1"}
        assert modal._snapshot is initial

        # The retry then sees no live reservations and completes normally.
        await wait_for(pilot, lambda: not modal._pending, timeout=5.0)
        await wait_for(pilot, lambda: modal._snapshot is refreshed, timeout=5.0)


async def test_usage_modal_update_summary_reports_failures(monkeypatch) -> None:
    initial = usage_view_snapshot(usage_provider("codex"))
    failed = usage_view_snapshot(
        usage_provider("codex", collection_status="error", diagnostic="timeout")
    )
    receipt = _receipt(provider="codex", operation_id="op-1", status="reserved")
    monkeypatch.setattr(usage_modal, "submit_usage_refresh", lambda *a, **k: receipt)
    monkeypatch.setattr(
        usage_modal, "list_provider_usage_refresh_reservations", lambda: ()
    )
    calls = {"n": 0}

    def load_snapshot() -> object:
        calls["n"] += 1
        return initial if calls["n"] == 1 else failed

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(initial, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_update_usage()
        await wait_for(pilot, lambda: modal._pending == {"codex": "op-1"})

        await wait_for(pilot, lambda: modal._snapshot is failed, timeout=5.0)

        messages = [call.args[0] for call in modal.notify.call_args_list]
        assert any("failed" in message for message in messages)


async def test_usage_modal_reopen_attaches_to_in_flight_refresh(monkeypatch) -> None:
    snapshot = usage_view_snapshot(usage_provider("codex"))
    monkeypatch.setattr(usage_modal, "eligible_usage_providers", lambda: ())
    monkeypatch.setattr(
        usage_modal,
        "list_provider_usage_refresh_reservations",
        lambda: (_reservation("codex", "op-1"),),
    )
    submit = MagicMock()
    monkeypatch.setattr(usage_modal, "submit_usage_refresh", submit)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._pending == {"codex": "op-1"})

        submit.assert_not_called()
        option_list = modal.query_one("#provider-usage-list", OptionList)
        assert "Updating" in option_list.get_option_at_index(0).prompt.plain


async def test_usage_modal_reopen_attaches_to_inline_owned_refresh(
    monkeypatch,
) -> None:
    snapshot = usage_view_snapshot(usage_provider("codex"))
    monkeypatch.setattr(usage_modal, "eligible_usage_providers", lambda: ())
    monkeypatch.setattr(
        usage_modal,
        "list_provider_usage_refresh_reservations",
        lambda: (_reservation("codex", "usage-job:abc123"),),
    )
    submit = MagicMock()
    monkeypatch.setattr(usage_modal, "submit_usage_refresh", submit)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._pending == {"codex": "usage-job:abc123"})

        submit.assert_not_called()
        option_list = modal.query_one("#provider-usage-list", OptionList)
        assert "Updating" in option_list.get_option_at_index(0).prompt.plain


async def test_usage_modal_preserves_selection_across_reload() -> None:
    before = usage_view_snapshot(usage_provider("claude"), usage_provider("codex"))
    after = usage_view_snapshot(
        usage_provider("claude"), usage_provider("codex", plan="Team")
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(before, load_snapshot=lambda: after)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#provider-usage-list", OptionList)
        option_list.highlighted = option_list.get_option_index("codex")

        modal._start_snapshot_load(keep_provider="codex", scan_conflicts=False)
        await wait_for(pilot, lambda: modal._snapshot is after)

        assert modal._highlighted_provider() == "codex"


def test_usage_modal_snapshot_failure_reports_warning() -> None:
    modal = ProviderUsageModal(usage_view_snapshot(usage_provider("codex")))
    failed_worker = SimpleNamespace(result=None, error=RuntimeError("store locked"))
    modal._snapshot_worker = failed_worker
    modal.notify = MagicMock()  # type: ignore[method-assign]

    modal._on_snapshot_worker(
        SimpleNamespace(worker=failed_worker, state=WorkerState.ERROR)
    )

    modal.notify.assert_any_call(
        "Could not load cached usage: store locked",
        severity="warning",
    )


def test_usage_modal_unmount_cancels_active_workers() -> None:
    modal = ProviderUsageModal(usage_view_snapshot(usage_provider("codex")))
    snapshot_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    update_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    modal._snapshot_worker = snapshot_worker
    modal._update_worker = update_worker

    modal.on_unmount()

    snapshot_worker.cancel.assert_called_once_with()
    update_worker.cancel.assert_called_once_with()


async def test_usage_modal_empty_snapshot_shows_placeholder() -> None:
    snapshot = usage_view_snapshot()

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderUsageModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#provider-usage-list", OptionList)
        assert option_list.option_count == 1
        assert option_list.get_option_at_index(0).disabled is True
