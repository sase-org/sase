"""Typed editor and preview-flow widget tests for the Config Center edit modal."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml
from textual.containers import VerticalScroll
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


async def test_edit_string_writes_to_target(tmp_path: Path) -> None:
    view, user_file = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    field = view.fields_by_path["timezone"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        result = await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "string"
        assert modal._target == "user"
        modal.query_one("#config-edit-input", SingleLineVimTextArea).text = "UTC"
        modal.action_confirm()  # plan
        await page.wait_for(lambda _s: modal._plan is not None)
        plan = modal._plan
        assert plan is not None
        assert modal._stage == "preview"
        assert "UTC" in plan.text_diff
        modal.action_confirm()  # write
        await page.wait_for(lambda _s: bool(result))
        assert result[0] is not None  # dismissed with the AppliedResult
        assert result[0].path == str(user_file)
    written = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert written["timezone"] == "UTC"


async def test_edit_back_from_preview_returns_to_edit(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        modal.query_one("#config-edit-input", SingleLineVimTextArea).text = "UTC"
        modal.action_confirm()
        await page.wait_for(lambda _s: modal._plan is not None)
        modal.action_back()  # back to edit
        await page.pause()
        assert modal._stage == "edit"
        assert modal._plan is None


async def test_preview_scroll_keys_move_preview_region(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage(size=(120, 24)) as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        modal.query_one("#config-edit-input", SingleLineVimTextArea).text = "UTC"
        modal.action_confirm()
        await page.wait_for(lambda _s: modal._plan is not None)
        assert modal._plan is not None
        modal._plan = replace(
            modal._plan,
            text_diff="\n".join(
                f"+expanded preview line {index:02d}" for index in range(80)
            ),
        )
        modal._render_all()
        await page.pause()

        scroll = modal.query_one("#config-edit-preview-scroll", VerticalScroll)
        await page.wait_for(
            lambda _s: scroll.allow_vertical_scroll and scroll.max_scroll_y > 0
        )
        assert scroll.scroll_y == 0

        await page.press("j")
        await page.wait_for(lambda _s: scroll.scroll_y > 0)
        await page.press("g")
        await page.wait_for(lambda _s: scroll.scroll_y == 0)
        await page.press("G")
        await page.wait_for(lambda _s: scroll.scroll_y == scroll.max_scroll_y)
        await page.press("ctrl+u")
        await page.wait_for(lambda _s: scroll.scroll_y < scroll.max_scroll_y)


async def test_bool_toggle_and_write(tmp_path: Path) -> None:
    view, user_file = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    field = view.fields_by_path["use_chezmoi"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        result = await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "bool"
        assert modal._bool_value is False
        await page.press("space")  # toggle to True via the screen binding
        await page.wait_for(lambda _s: modal._bool_value is True)
        modal.action_confirm()  # plan
        await page.wait_for(lambda _s: modal._plan is not None)
        modal.action_confirm()  # write
        await page.wait_for(lambda _s: bool(result))
    written = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert written["use_chezmoi"] is True


async def test_enum_navigation_digits_and_space(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {})
    field = view.fields_by_path["mode"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "enum"
        assert modal._enum_index == 0
        assert "1. auto" in modal._value_text().plain

        await page.press("j")
        await page.wait_for(lambda _s: modal._enum_index == 1)
        await page.press("k")
        await page.wait_for(lambda _s: modal._enum_index == 0)
        await page.press("3")
        await page.wait_for(lambda _s: modal._enum_index == 2)
        await page.press("space")
        await page.wait_for(lambda _s: modal._enum_index == 0)


async def test_bool_digit_picks_visible_option(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {})
    field = view.fields_by_path["use_chezmoi"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await open_config_edit_modal(page, modal)
        assert "1. true" in modal._value_text().plain
        await page.press("1")
        await page.wait_for(lambda _s: modal._bool_value is True)
        await page.press("2")
        await page.wait_for(lambda _s: modal._bool_value is False)


async def test_scalar_input_selects_all_on_open(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        assert editor.selected_text == "US/Pacific"


async def test_multiline_string_uses_textarea(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["notes"])
        await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "text"
        editor = modal.query_one("#config-edit-textarea", TextArea)
        assert editor.text == "line 1\nline 2"


async def test_yaml_textarea_uses_yaml_language(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"linked_repos": [{"name": "core"}]})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["linked_repos"])
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-textarea", TextArea)
        assert getattr(editor, "language", None) == "yaml"
