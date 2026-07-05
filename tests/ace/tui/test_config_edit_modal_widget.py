"""Widget-level tests for the Config Center edit modal (Phase 5).

These stand up the modal inside a real Textual app and drive the full
edit → preview → write flow that the pure helpers cannot reach: the worker-backed
plan, the typed editors (string / bool), scope cycling, reset-to-default,
and validation blocking the write. Writes land in a temporary ``sase.yml``
(chezmoi remapping is patched off) so the on-disk result can be asserted.
"""

from __future__ import annotations

from dataclasses import replace
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from textual.containers import VerticalScroll
from textual.widgets import TextArea

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_edit_modal as cem
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal, _OverlayNameModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.config.core import ConfigLayer
from sase.config.edit import (
    AppliedResult,
    ConfigEffectivePreview,
    ConfigWritePlan,
    EditPlanResult,
)
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
        "mode": {
            "type": "string",
            "enum": ["auto", "manual", "off"],
            "default": "auto",
        },
        "notes": {
            "type": "string",
            "default": "line 1\nline 2",
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
        "ace": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "lumberjack": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    "default": {
                        "checks": {
                            "description": "Run checks.",
                            "interval": "300s",
                        }
                    },
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
                "mode": "auto",
                "notes": "line 1\nline 2",
                "use_chezmoi": False,
                "axe": {"max_hook_runners": 3, "chop_script_dirs": []},
                "ace": {
                    "lumberjack": {
                        "checks": {
                            "description": "Run checks.",
                            "interval": "300s",
                        }
                    }
                },
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


def _large_lumberjack_value(count: int = 50) -> dict[str, Any]:
    return {
        f"job_{index:03d}": {
            "description": (
                f"Background maintenance job {index:03d} with a deliberately "
                "long sentence that should not soft-wrap inside the edit modal."
            ),
            "interval": f"{300 + index}s",
            "command": f"sase axe chop job_{index:03d}",
        }
        for index in range(count)
    }


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
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
        modal.query_one("#config-edit-input", SingleLineVimTextArea).text = "UTC"
        modal.action_confirm()
        await page.wait_for(lambda _s: modal._plan is not None)
        modal.action_back()  # back to edit
        await page.pause()
        assert modal._stage == "edit"
        assert modal._plan is None


async def test_preview_scroll_keys_move_preview_region(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage(size=(120, 24)) as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
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
        await page.wait_for(lambda _s: scroll.max_scroll_y > 0)
        assert scroll.scroll_y == 0

        await page.press("j")
        await page.wait_for(lambda _s: scroll.scroll_y > 0)
        await page.press("g")
        await page.wait_for(lambda _s: scroll.scroll_y == 0)
        await page.press("G")
        await page.wait_for(lambda _s: scroll.scroll_y == scroll.max_scroll_y)
        await page.press("ctrl+u")
        await page.wait_for(lambda _s: scroll.scroll_y < scroll.max_scroll_y)


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


async def test_enum_navigation_digits_and_space(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {})
    field = view.fields_by_path["mode"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await _open(page, modal)
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
    view, _ = _view(tmp_path, {})
    field = view.fields_by_path["use_chezmoi"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await _open(page, modal)
        assert "1. true" in modal._value_text().plain
        await page.press("1")
        await page.wait_for(lambda _s: modal._bool_value is True)
        await page.press("2")
        await page.wait_for(lambda _s: modal._bool_value is False)


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
        scope_text = modal._scope_text().plain
        assert "user" in scope_text
        assert "replace" in scope_text
        assert "overlay:sase_extra.yml" in scope_text
        assert "concatenate" in scope_text


async def test_scope_selector_row_pick_changes_target(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
        writable = [s.name for s in modal._writable_sources()]
        assert len(writable) > 1
        modal._select_scope_index(1)
        await page.pause()
        assert modal._target == writable[1]


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
        name_modal.query_one(
            "#overlay-name-input", SingleLineVimTextArea
        ).text = "scratch"
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
        modal.query_one(
            "#config-edit-input", SingleLineVimTextArea
        ).text = "99"  # > max 9
        modal.action_confirm()
        await page.pause()
        assert modal._stage == "edit"  # never advanced to preview
        assert modal._plan is None
        assert modal._error is not None


async def test_live_validation_error_appears_and_clears(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {"axe": {"max_hook_runners": 3}})
    field = view.fields_by_path["axe.max_hook_runners"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await _open(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        editor.text = "99"
        await page.wait_for(lambda _s: modal._error is not None)
        assert "must be" in (modal._error or "")
        editor.text = "5"
        await page.wait_for(lambda _s: modal._error is None)


async def test_scalar_input_selects_all_on_open(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        assert editor.selected_text == "US/Pacific"


async def test_multiline_string_uses_textarea(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["notes"])
        await _open(page, modal)
        assert modal._editor_kind == "text"
        editor = modal.query_one("#config-edit-textarea", TextArea)
        assert editor.text == "line 1\nline 2"


async def test_yaml_textarea_uses_yaml_language(tmp_path: Path) -> None:
    view, _ = _view(tmp_path, {"linked_repos": [{"name": "core"}]})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["linked_repos"])
        await _open(page, modal)
        editor = modal.query_one("#config-edit-textarea", TextArea)
        assert getattr(editor, "language", None) == "yaml"


async def test_large_yaml_value_keeps_editor_and_hints_visible(
    tmp_path: Path,
) -> None:
    large_value = _large_lumberjack_value()
    view, _ = _view(tmp_path, {"ace": {"lumberjack": large_value}})
    async with AcePage(size=(120, 40)) as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["ace.lumberjack"])
        await _open(page, modal)
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


# --- chezmoi apply targets the home path, not the source ------------------


async def test_chezmoi_write_applies_home_target_not_source(tmp_path: Path) -> None:
    """A chezmoi-backed write runs ``chezmoi apply`` on the home target path.

    Regression: the modal previously handed the chezmoi *source* path to
    ``chezmoi apply``, which rejects it as "not in source state". The apply must
    receive the original home target (``plan.write_plan.file``).
    """
    view, user_file = _view(tmp_path, {"timezone": "US/Pacific"})
    field = view.fields_by_path["timezone"]
    home_target = str(user_file)
    source_path = str(
        tmp_path / "chezmoi" / "home" / "dot_config" / "sase" / "sase.yml"
    )

    plan = EditPlanResult(
        schema_version=1,
        write_plan=ConfigWritePlan(
            file=home_target,
            layer="user",
            key_path=("timezone",),
            op="set",
            has_value=True,
            new_value="UTC",
        ),
        candidate_config={},
        effective_preview=ConfigEffectivePreview(
            path="timezone",
            has_before=True,
            before="US/Pacific",
            has_after=True,
            after="UTC",
            changed=True,
        ),
        validation=(),
        diagnostics=(),
        target_path=source_path,
        used_chezmoi=True,
        current_text="timezone: US/Pacific\n",
        new_text="timezone: UTC\n",
        text_diff="@@ -1 +1 @@\n-timezone: US/Pacific\n+timezone: UTC\n",
    )
    applied = AppliedResult(
        path=source_path,
        op="set",
        key_path=("timezone",),
        created=False,
        used_chezmoi=True,
    )
    apply_chezmoi_mock = MagicMock(
        return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")
    )

    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        result = await _open(page, modal)
        with (
            patch.object(cem, "plan_config_edit", return_value=plan),
            patch.object(cem, "apply_config_edit", return_value=applied),
            patch.object(cem, "apply_chezmoi", apply_chezmoi_mock),
        ):
            modal.action_confirm()  # plan
            await page.wait_for(lambda _s: modal._plan is not None)
            modal.action_confirm()  # write
            await page.wait_for(lambda _s: bool(result))

    apply_chezmoi_mock.assert_called_once_with(home_target)
    assert result[0] is not None


# --- vim-mode editing in the text editors (sase vim adoption) -------------


async def test_two_stage_escape_backs_out_of_modal(tmp_path: Path) -> None:
    """Esc enters NORMAL mode; a second Esc (nothing pending) backs out."""
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        result = await _open(page, modal)
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
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
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
    view, _ = _view(tmp_path, {"axe": {"max_hook_runners": 3}})
    field = view.fields_by_path["axe.max_hook_runners"]
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        await _open(page, modal)
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
    view, _ = _view(tmp_path, {"linked_repos": [{"name": "core"}]})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["linked_repos"])
        await _open(page, modal)
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
    view, _ = _view(tmp_path, {"linked_repos": [{"name": "core"}]})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["linked_repos"])
        await _open(page, modal)
        assert modal._editor_kind == "yaml"
        editor = modal.query_one("#config-edit-textarea", VimTextArea)
        editor.focus()
        await page.press("ctrl+s")  # bubbles past the editor to the modal binding
        await page.wait_for(lambda _s: modal._stage == "preview")


async def test_ctrl_r_toggles_reset_from_insert_mode(tmp_path: Path) -> None:
    """NORMAL-mode ``ctrl+r`` is vim redo, but INSERT-mode reaches the modal."""
    view, _ = _view(tmp_path, {"timezone": "US/Pacific"})
    async with AcePage() as page:
        modal = ConfigEditModal(view, field=view.fields_by_path["timezone"])
        await _open(page, modal)
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        assert editor._vim_mode == "insert"
        assert modal._op_unset is False
        editor.focus()
        await page.press("ctrl+r")  # not consumed in INSERT -> modal toggle_reset
        await page.wait_for(lambda _s: modal._op_unset is True)
