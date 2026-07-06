"""Scope-selection widget tests for the Config Center edit modal."""

from __future__ import annotations

from pathlib import Path

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal, _OverlayNameModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from tests.ace.tui._config_edit_modal_widget_helpers import (
    _no_chezmoi as _no_chezmoi,
)
from tests.ace.tui._config_edit_modal_widget_helpers import (
    config_edit_view,
    open_config_edit_modal,
)


async def test_cycle_scope_changes_target(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        first = modal._target
        modal.action_cycle_scope()
        await page.pause()
        assert modal._target != first
        assert modal._target in {s.name for s in view.inventory.sources if s.writable}
        scope_text = modal._scope_text().plain
        assert "user" in scope_text
        assert "replace" in scope_text
        assert "overlay:sase_extra.yml" in scope_text
        assert "concatenate" in scope_text


async def test_scope_selector_row_pick_changes_target(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        writable = [s.name for s in modal._writable_sources()]
        assert len(writable) > 1
        modal._select_scope_index(1)
        await page.pause()
        assert modal._target == writable[1]


async def test_new_overlay_switches_scope_to_created_overlay(tmp_path: Path) -> None:
    view, _ = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await open_config_edit_modal(page, modal)
        modal.action_new_overlay()  # pushes the overlay-name prompt
        await page.expect_modal("_OverlayNameModal")
        name_modal = page.app.screen
        assert isinstance(name_modal, _OverlayNameModal)
        await page.wait_for(lambda _s: bool(name_modal.query("#overlay-name-input")))
        name_modal.query_one(
            "#overlay-name-input", SingleLineVimTextArea
        ).text = "scratch"
        name_modal.action_submit()
        await page.wait_for(lambda _s: modal._target == "overlay:sase_scratch.yml")
        # The created overlay is now a writable, not-yet-existing target.
        source = modal._inventory.source("overlay:sase_scratch.yml")
        assert source is not None and source.writable and not source.exists
