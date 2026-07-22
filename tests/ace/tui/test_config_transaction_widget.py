"""Shared transaction conflict and teardown coverage through Config Center."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from unittest.mock import patch

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_edit_modal as cem
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from sase.ace.tui.modals.config_transaction import ConfigTransactionConflict
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from tests.ace.tui._config_edit_modal_widget_helpers import (
    _no_chezmoi as _no_chezmoi,
)
from tests.ace.tui._config_edit_modal_widget_helpers import (
    config_edit_view,
    open_config_edit_modal,
)


async def test_apply_conflict_preserves_draft_and_returns_to_replan(
    tmp_path: Path,
) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        editor.text = "UTC"
        modal.action_confirm()
        await page.wait_for(lambda _screen: modal._plan is not None)
        with patch.object(
            cem,
            "apply_config_edit",
            side_effect=ConfigTransactionConflict("stale write conflict"),
        ):
            modal.action_confirm()
            await page.wait_for(lambda _screen: modal._transaction_conflict)
        assert modal._stage == "edit"
        assert editor.text == "UTC"
        assert "stale write" in (modal._error or "")
        modal.action_reload_transaction()
        assert not modal._transaction_conflict
        assert "preserved draft" in (modal._status or "")


async def test_plan_worker_is_cancelled_and_late_result_ignored_on_unmount(
    tmp_path: Path,
) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    entered = Event()
    release = Event()
    original = cem.plan_config_edit

    def blocked(*args: object, **kwargs: object) -> object:
        entered.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        modal.query_one("#config-edit-input", SingleLineVimTextArea).text = "UTC"
        with patch.object(cem, "plan_config_edit", side_effect=blocked):
            modal.action_confirm()
            await page.wait_for(lambda _screen: entered.is_set())
            worker = modal._plan_worker
            assert worker is not None
            modal.dismiss(None)
            await page.expect_no_modal()
            await page.wait_for(lambda _screen: worker.is_cancelled)
            release.set()
            await page.pause()
            assert modal._plan is None
