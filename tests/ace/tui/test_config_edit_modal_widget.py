"""Widget-level tests for the Config Center edit modal (Phase 5).

These stand up the modal inside a real Textual app and drive the full
edit → preview → write flow that the pure helpers cannot reach: the worker-backed
plan, the typed editors (string / bool), scope cycling, reset-to-default,
and validation blocking the write. Writes land in a temporary ``sase.yml``
(chezmoi remapping is patched off) so the on-disk result can be asserted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from textual.widgets import Input, TextArea

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal, _OverlayNameModal
from sase.config.core import ConfigLayer
from sase.config.inventory import build_config_inventory, config_field_model


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "timezone": {
            "type": "string",
            "default": "America/New_York",
            "description": "IANA timezone.",
        },
        "use_chezmoi": {"type": "boolean", "default": False},
        "axe": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "max_hook_runners": {
                    "type": "integer",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 9,
                },
                "chop_script_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
            },
        },
        "linked_repos": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
            "default": [],
        },
        "sibling_repos": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    },
}


def _view(tmp_path: Path, user_data: dict[str, Any]) -> tuple[cp.ConfigPaneView, Path]:
    """A view over a [default, user, overlay] stack backed by a real user file."""
    user_file = tmp_path / "sase.yml"
    user_file.write_text(yaml.safe_dump(user_data), encoding="utf-8")
    overlay_file = tmp_path / "sase_extra.yml"
    overlay_file.write_text("axe:\n  chop_script_dirs:\n    - over\n", encoding="utf-8")
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "timezone": "America/New_York",
                "use_chezmoi": False,
                "axe": {"max_hook_runners": 3, "chop_script_dirs": []},
                "linked_repos": [],
            },
        ),
        ConfigLayer(
            name="user",
            path=str(user_file),
            exists=True,
            list_strategy="replace",
            data=user_data,
        ),
        ConfigLayer(
            name="overlay:sase_extra.yml",
            path=str(overlay_file),
            exists=True,
            list_strategy="concatenate",
            data={"axe": {"chop_script_dirs": ["over"]}},
        ),
    ]
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        inventory = build_config_inventory(schema=_SCHEMA)
    field_model = config_field_model(schema=_SCHEMA)
    return cp.ConfigPaneView.build(field_model, inventory), user_file


async def _open(page: AcePage, modal: ConfigEditModal) -> list[Any]:
    """Push *modal* and return a list that receives its dismiss result."""
    result: list[Any] = []
    page.app.push_screen(modal, result.append)
    await page.expect_modal("ConfigEditModal")
    await page.pause()
    return result


@pytest.fixture(autouse=True)
def _no_chezmoi() -> Any:
    """Pin chezmoi off so writes land in the temp file, not a source tree."""
    with patch("sase.config.edit.get_use_chezmoi", return_value=False):
        yield


# --- string edit -> preview -> write --------------------------------------


async def test_edit_string_writes_to_target(tmp_path: Path) -> None:
    view, user_file = _view(tmp_path, {"timezone": "US/Pacific"})
    field = view.fields_by_path["timezone"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        result = await _open(page, modal)
        assert modal._editor_kind == "string"
        assert modal._target == "user"
        modal.query_one("#config-edit-input", Input).value = "UTC"
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
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
        modal.query_one("#config-edit-input", Input).value = "UTC"
        modal.action_confirm()
        await page.wait_for(lambda _s: modal._plan is not None)
        modal.action_back()  # back to edit
        await page.pause()
        assert modal._stage == "edit"
        assert modal._plan is None


# --- boolean toggle via keystrokes ----------------------------------------


async def test_bool_toggle_and_write(tmp_path: Path) -> None:
    view, user_file = _view(tmp_path, {"timezone": "US/Pacific"})
    field = view.fields_by_path["use_chezmoi"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        result = await _open(page, modal)
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


# --- scope cycling ---------------------------------------------------------


async def test_cycle_scope_changes_target(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
        first = modal._target
        modal.action_cycle_scope()
        await page.pause()
        assert modal._target != first
        assert modal._target in {s.name for s in view.inventory.sources if s.writable}


async def test_new_overlay_switches_scope_to_created_overlay(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
        modal.action_new_overlay()  # pushes the overlay-name prompt
        await page.expect_modal("_OverlayNameModal")
        name_modal = page.app.screen
        assert isinstance(name_modal, _OverlayNameModal)
        await page.wait_for(lambda _s: bool(name_modal.query("#overlay-name-input")))
        name_modal.query_one("#overlay-name-input", Input).value = "scratch"
        name_modal.action_submit()
        await page.wait_for(lambda _s: modal._target == "overlay:sase_scratch.yml")
        # The created overlay is now a writable, not-yet-existing target.
        source = modal._inventory.source("overlay:sase_scratch.yml")
        assert source is not None and source.writable and not source.exists


# --- reset to default ------------------------------------------------------


async def test_reset_to_default_plans_unset(tmp_path: Path) -> None:
    view, user_file = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        result = await _open(page, modal)
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


# --- validation blocks the write ------------------------------------------


async def test_client_constraint_blocks_plan(tmp_path: Path) -> None:
    """An out-of-range number is rejected client-side before any plan/preview."""
    view, _ = _view(tmp_path, {"axe": {"max_hook_runners": 3}})
    field = view.fields_by_path["axe.max_hook_runners"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await _open(page, modal)
        modal.query_one("#config-edit-input", Input).value = "99"  # > maximum 9
        modal.action_confirm()
        await page.pause()
        assert modal._stage == "edit"  # never advanced to preview
        assert modal._plan is None
        assert modal._error is not None


async def test_schema_validation_blocks_write(tmp_path: Path) -> None:
    """A candidate that fails schema validation cannot be written."""
    view, user_file = _view(tmp_path, {"linked_repos": [{"name": "core"}]})
    field = view.fields_by_path["linked_repos"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        result = await _open(page, modal)
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
