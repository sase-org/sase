"""Layout-state widget tests for the Config Center edit modal."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import TextArea

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from tests.ace.tui._config_edit_modal_widget_helpers import (
    _no_chezmoi as _no_chezmoi,
)
from tests.ace.tui._config_edit_modal_widget_helpers import (
    config_edit_view,
    large_lumberjack_value,
    open_config_edit_modal,
)


async def test_large_yaml_value_keeps_editor_and_hints_visible(
    tmp_path: Path,
) -> None:
    large_value = large_lumberjack_value()
    view, _ = config_edit_view(tmp_path, {"ace": {"lumberjack": large_value}})
    async with AcePage(size=(120, 40)) as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["ace.lumberjack"])
        await open_config_edit_modal(page, modal)
        editor = modal.query_one("#config-edit-textarea", TextArea)
        hints = modal.query_one("#config-edit-hints")

        await page.wait_for(
            lambda _s: editor.region.height > 0 and hints.region.height > 0
        )

        assert editor.display is True
        assert hints.display is True
        assert editor.region.y < hints.region.y
        assert hints.region.y + hints.region.height <= page.app.size.height
        assert "more line(s)" in modal._info_text().plain
        assert "job_049" in editor.text


async def test_expanded_class_tracks_multiline_preview_and_reset_states(
    tmp_path: Path,
) -> None:
    large_value = large_lumberjack_value()
    view, _ = config_edit_view(tmp_path, {"ace": {"lumberjack": large_value}})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["ace.lumberjack"])
        await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "yaml"
        assert modal.has_class("-expanded")

        modal.action_toggle_reset()
        await page.wait_for(lambda _s: modal._op_unset)
        assert not modal.has_class("-expanded")

        modal.action_toggle_reset()
        await page.wait_for(lambda _s: not modal._op_unset)
        assert modal.has_class("-expanded")

    scalar_view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(
            scalar_view, field=scalar_view.fields_by_path["timezone"]
        )
        await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "string"
        assert not modal.has_class("-expanded")

        modal.query_one("#config-edit-input", SingleLineVimTextArea).text = "UTC"
        modal.action_confirm()
        await page.wait_for(lambda _s: modal._plan is not None)
        assert modal.has_class("-expanded")

        modal.action_back()
        await page.wait_for(lambda _s: modal._stage == "edit")
        assert not modal.has_class("-expanded")

    bool_view, _ = config_edit_view(tmp_path, {})
    async with AcePage() as page:
        modal = ConfigEditModal(
            bool_view, field=bool_view.fields_by_path["use_chezmoi"]
        )
        await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "bool"
        assert not modal.has_class("-expanded")

    enum_view, _ = config_edit_view(tmp_path, {})
    async with AcePage() as page:
        modal = ConfigEditModal(enum_view, field=enum_view.fields_by_path["mode"])
        await open_config_edit_modal(page, modal)
        assert modal._editor_kind == "enum"
        assert not modal.has_class("-expanded")
