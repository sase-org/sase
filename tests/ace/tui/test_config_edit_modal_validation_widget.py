"""Reset and validation widget tests for the Config Center edit modal."""

from __future__ import annotations

from pathlib import Path

import yaml
from textual.widgets import TextArea

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from tests.ace.tui._config_edit_modal_widget_helpers import (
    _no_chezmoi as _no_chezmoi,
)
from tests.ace.tui._config_edit_modal_widget_helpers import (
    config_edit_view,
    open_config_edit_modal,
)


async def test_reset_to_default_plans_unset(tmp_path: Path) -> None:
    view, user_file = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        result = await open_config_edit_modal(page, modal)
        modal.action_toggle_reset()
        await page.pause()
        assert modal._op_unset is True
        modal.action_confirm()  # plan the unset
        await page.wait_for(lambda _s: modal._plan is not None)
        plan = modal._plan
        assert plan is not None
        assert plan.write_plan.op == "unset"
        modal.action_confirm()  # write
        await page.wait_for(lambda _s: bool(result))
    written = yaml.safe_load(user_file.read_text(encoding="utf-8")) or {}
    assert "timezone" not in written


async def test_client_constraint_blocks_plan(tmp_path: Path) -> None:
    """An out-of-range number is rejected client-side before any plan/preview."""
    view, _ = config_edit_view(tmp_path, {"axe": {"max_hook_runners": 3}})
    field = view.fields_by_path["axe.max_hook_runners"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await open_config_edit_modal(page, modal)
        modal.query_one(
            "#config-edit-input", SingleLineVimTextArea
        ).text = "99"  # > max 9
        modal.action_confirm()
        await page.pause()
        assert modal._stage == "edit"  # never advanced to preview
        assert modal._plan is None
        assert modal._error is not None


async def test_live_validation_error_appears_and_clears(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"axe": {"max_hook_runners": 3}})
    field = view.fields_by_path["axe.max_hook_runners"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        editor.text = "99"
        await page.wait_for(lambda _s: modal._error is not None)
        assert "must be" in (modal._error or "")
        editor.text = "5"
        await page.wait_for(lambda _s: modal._error is None)


async def test_schema_validation_blocks_write(tmp_path: Path) -> None:
    """A candidate that fails schema validation cannot be written."""
    view, user_file = config_edit_view(tmp_path, {"linked_repos": [{"name": "core"}]})
    field = view.fields_by_path["linked_repos"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        result = await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "yaml"
        # 5 is not an array -> the merged candidate fails schema validation.
        modal.query_one("#config-edit-textarea", TextArea).text = "5"
        modal.action_confirm()  # plan
        await page.wait_for(lambda _s: modal._plan is not None)
        plan = modal._plan
        assert plan is not None
        assert plan.is_valid is False
        modal.action_confirm()  # attempt write -> blocked
        await page.pause()
        assert result == []  # not dismissed
        assert modal._error is not None
    # Nothing written.
    assert yaml.safe_load(user_file.read_text(encoding="utf-8")) == {
        "linked_repos": [{"name": "core"}]
    }
