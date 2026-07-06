"""Vim-mode editor widget tests for the Config Center edit modal."""

from __future__ import annotations

from pathlib import Path

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from tests.ace.tui._config_edit_modal_widget_helpers import (
    _no_chezmoi as _no_chezmoi,
)
from tests.ace.tui._config_edit_modal_widget_helpers import (
    config_edit_view,
    open_config_edit_modal,
)


async def test_two_stage_escape_backs_out_of_modal(tmp_path: Path) -> None:
    """Esc enters NORMAL mode; a second Esc (nothing pending) backs out."""
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        result = await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        editor.focus()
        await page.press("escape")  # INSERT -> NORMAL (consumed by the editor)
        await page.pause()
        assert editor._vim_mode == "normal"
        await page.expect_modal("ConfigEditModal")  # still open
        await page.press("escape")  # NORMAL, nothing pending -> modal backs out
        await page.expect_no_modal()
        assert result == [None]


async def test_enter_submits_from_normal_mode(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        editor.text = "UTC"
        editor.focus()
        await page.press("escape")  # INSERT -> NORMAL
        await page.pause()
        assert editor._vim_mode == "normal"
        await page.press("enter")  # submit from NORMAL mode
        await page.wait_for(lambda _s: modal._plan is not None)
        assert modal._stage == "preview"
        assert "UTC" in (modal._plan.text_diff if modal._plan else "")


async def test_normal_mode_edit_fires_live_validation(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"axe": {"max_hook_runners": 3}})
    field = view.fields_by_path["axe.max_hook_runners"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        editor.text = "99"  # > maximum 9 -> invalid
        await page.wait_for(lambda _s: modal._error is not None)
        editor.cursor_location = (0, 0)
        editor.focus()
        await page.press("escape")  # INSERT -> NORMAL
        await page.pause()
        assert editor._vim_mode == "normal"
        await page.press("x")  # delete a digit -> "9" (valid)
        await page.wait_for(lambda _s: modal._error is None)
        assert editor.text == "9"


async def test_normal_mode_dd_edits_yaml_editor(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"linked_repos": [{"name": "core"}]})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["linked_repos"])
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-textarea", VimTextArea)
        editor.text = "- name: core\n- name: extra"
        editor.cursor_location = (0, 0)
        editor.focus()
        await page.press("escape")  # INSERT -> NORMAL
        await page.pause()
        assert editor._vim_mode == "normal"
        await page.press("d", "d")  # delete the first line
        await page.pause()
        assert editor.text == "- name: extra"


async def test_ctrl_s_confirms_from_yaml_editor(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"linked_repos": [{"name": "core"}]})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["linked_repos"])
        await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "yaml"
        editor = modal.query_one("#config-edit-textarea", VimTextArea)
        editor.focus()
        await page.press("ctrl+s")  # bubbles past the editor to the modal binding
        await page.wait_for(lambda _s: modal._stage == "preview")


async def test_ctrl_r_toggles_reset_from_insert_mode(tmp_path: Path) -> None:
    """NORMAL-mode ``ctrl+r`` is vim redo, but INSERT-mode reaches the modal."""
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        assert editor._vim_mode == "insert"
        assert modal._op_unset is False
        editor.focus()
        await page.press("ctrl+r")  # not consumed in INSERT -> modal toggle_reset
        await page.wait_for(lambda _s: modal._op_unset is True)
