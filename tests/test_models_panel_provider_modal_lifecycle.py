"""Models-panel provider-routing modal snapshot and lifecycle tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from textual.widgets import OptionList, Static
from textual.worker import WorkerState

from sase.ace.tui.modals.models_panel_duration import DurationPickerModal
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._models_panel_provider_routing_helpers import (
    snapshot as _snapshot,
    status as _status,
)


async def test_provider_modal_initial_snapshot_does_not_emit_change() -> None:
    before = _snapshot(_status("claude"))
    after = _snapshot(_status("claude"), disables={})
    on_snapshot = MagicMock()

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: after,
            on_snapshot=on_snapshot,
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._snapshot is after)

    assert modal._changed is False
    on_snapshot.assert_not_called()


async def test_provider_modal_omits_hidden_provider_and_opens_duration() -> None:
    snapshot = _snapshot(
        _status("claude"),
        _status("fakey", hidden=True),
        _status("codex", cli_available=False),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#provider-routing-list", OptionList)
        ids = [str(option.id) for option in option_list.options]
        assert ids == ["claude", "codex"]

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, DurationPickerModal)
        title = pilot.app.screen.query_one("#provider-duration-title", Static)
        assert title.content == "Disable CLAUDE"


def test_provider_modal_snapshot_failure_reports_warning() -> None:
    modal = ProviderRoutingModal(_snapshot(_status("claude")))
    failed_worker = SimpleNamespace(
        result=None,
        error=RuntimeError("state file locked"),
    )
    modal._snapshot_worker = failed_worker
    modal.notify = MagicMock()  # type: ignore[method-assign]

    modal._on_snapshot_worker(
        SimpleNamespace(worker=failed_worker, state=WorkerState.ERROR)
    )

    modal.notify.assert_any_call(
        "Could not load provider routing: state file locked",
        severity="warning",
    )


async def test_provider_modal_cursor_survives_snapshot_refresh() -> None:
    before = _snapshot(_status("claude"), _status("codex"))
    after = _snapshot(_status("claude"), _status("codex", model_count=4))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: after)
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one("#provider-routing-list", OptionList)
        option_list.highlighted = option_list.get_option_index("codex")

        modal._apply_snapshot(after, keep_provider="codex", emit_snapshot=False)
        await pilot.pause()

        assert modal._highlighted_provider() == "codex"


def test_provider_modal_unmount_cancels_active_workers() -> None:
    modal = ProviderRoutingModal(_snapshot(_status("claude")))
    snapshot_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    write_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    modal._snapshot_worker = snapshot_worker
    modal._write_worker = write_worker

    modal.on_unmount()

    snapshot_worker.cancel.assert_called_once_with()
    write_worker.cancel.assert_called_once_with()


async def test_provider_modal_footer_names_soft_disable() -> None:
    snapshot = _snapshot(_status("claude"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()
        footer = modal.query_one("#provider-routing-footer", Static)
        assert "Soft disable" in str(footer.content)
        assert "d/enter" in str(footer.content)
