"""Tests for the model-alias edit plan, preview, and write modal."""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

from textual.widgets import Static

import sase.ace.tui.modals.models_panel_edit as models_panel_edit
from sase.ace.tui.modals.models_panel_edit import AliasEditPreviewModal
from sase.ace.tui.modals.models_panel_edit_helpers import AliasEditOutcome
from sase.config import AppliedResult, ConfigEditOp
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_edit_plan,
    wait_for,
)


async def test_preview_modal_renders_plan(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._plan is not None)
        # The preview Static is mounted and the rendered body reflects the plan.
        assert modal.query_one("#alias-edit-preview", Static) is not None
        text = modal._body_text().plain
        assert "coder" in text
        assert "opus" in text


async def test_preview_modal_confirm_writes_and_dismisses(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )
    applied = AppliedResult(
        path="/tmp/sase.yml",
        op="set",
        key_path=("llm_provider", "model_aliases", "builtin", "coder"),
        created=False,
        used_chezmoi=False,
    )
    apply_mock = MagicMock(return_value=applied)
    monkeypatch.setattr(models_panel_edit, "apply_config_edit", apply_mock)
    result: list[Any] = []

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal, result.append)
        await wait_for(pilot, lambda: modal._plan is not None)
        modal.action_confirm()
        await wait_for(pilot, lambda: bool(result))

    apply_mock.assert_called_once()
    assert isinstance(result[0], AliasEditOutcome)
    assert result[0].alias == "coder"


async def test_preview_modal_chezmoi_applies_home_target_not_source(
    monkeypatch: Any,
) -> None:
    """A chezmoi-backed write runs ``chezmoi apply`` on the home target path.

    Regression: the modal previously handed the chezmoi *source* path to
    ``chezmoi apply``, which rejects it as "not in source state". The apply must
    receive the original home target (``plan.write_plan.file``).
    """
    home_target = "/home/u/.config/sase/sase.yml"
    source_path = "/home/u/.local/share/chezmoi/home/dot_config/sase/sase.yml"
    monkeypatch.setattr(
        models_panel_edit,
        "plan_alias_edit",
        lambda *a, **k: make_edit_plan(used_chezmoi=True, target_path=home_target),
    )
    applied = AppliedResult(
        path=source_path,
        op="set",
        key_path=("llm_provider", "model_aliases", "builtin", "coder"),
        created=False,
        used_chezmoi=True,
    )
    monkeypatch.setattr(
        models_panel_edit, "apply_config_edit", MagicMock(return_value=applied)
    )
    apply_chezmoi_mock = MagicMock(
        return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")
    )
    monkeypatch.setattr(models_panel_edit, "apply_chezmoi", apply_chezmoi_mock)
    result: list[Any] = []

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal, result.append)
        await wait_for(pilot, lambda: modal._plan is not None)
        modal.action_confirm()
        await wait_for(pilot, lambda: bool(result))

    apply_chezmoi_mock.assert_called_once_with(home_target)
    assert isinstance(result[0], AliasEditOutcome)


async def test_preview_modal_no_change_blocks_write(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        models_panel_edit,
        "plan_alias_edit",
        lambda *a, **k: make_edit_plan(diff="   \n"),
    )
    apply_mock = MagicMock()
    monkeypatch.setattr(models_panel_edit, "apply_config_edit", apply_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._plan is not None)
        modal.action_confirm()
        await pilot.pause()
        apply_mock.assert_not_called()
        assert modal._error is not None


async def test_preview_modal_cancel_dismisses_none(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )
    result: list[Any] = []

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal, result.append)
        await wait_for(pilot, lambda: modal._plan is not None)
        await pilot.press("escape")
        await wait_for(pilot, lambda: bool(result))

    assert result[0] is None
