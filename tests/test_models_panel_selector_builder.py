"""Tests for the guided pool / fallback :class:`SelectorBuilderModal`."""

from __future__ import annotations

from unittest.mock import MagicMock

from textual.widgets import OptionList

from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
from sase.ace.tui.modals.model_picker_modal import CUSTOM_SENTINEL
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
)
from sase.ace.tui.modals.models_panel_selector_builder import SelectorBuilderModal
from sase.llm_provider import AliasView, EffectiveDefaultEffortSnapshot
from tests._model_picker_modal_helpers import ModelPickerTestApp, make_alias_context
from tests._models_panel_helpers import make_alias_view


def _snapshot(configured_effort: str | None = "high") -> EffectiveDefaultEffortSnapshot:
    return EffectiveDefaultEffortSnapshot(
        configured_effort=configured_effort,
        temporary_override=None,
        captured_at=0.0,
    )


def _modal(
    current_value: str, views: list[AliasView] | None = None
) -> SelectorBuilderModal:
    return SelectorBuilderModal(
        alias="blogger",
        current_value=current_value,
        alias_context=make_alias_context(target="blogger", views=views),
        effort_snapshot=_snapshot(),
        now=0.0,
    )


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def test_seed_from_existing_pool() -> None:
    modal = _modal("claude/opus | codex/o3")
    assert modal._mode == "round_robin"
    assert modal._members == ["claude/opus", "codex/o3"]


def test_seed_from_existing_fallback() -> None:
    modal = _modal("claude/opus || codex/o3")
    assert modal._mode == "fallback"
    assert modal._members == ["claude/opus", "codex/o3"]


def test_seed_from_single_target() -> None:
    modal = _modal("claude/opus")
    assert modal._mode == "round_robin"
    assert modal._members == ["claude/opus"]


def test_seed_from_empty() -> None:
    modal = _modal("")
    assert modal._mode == "round_robin"
    assert modal._members == []


# ---------------------------------------------------------------------------
# Validation text
# ---------------------------------------------------------------------------


def test_validation_text_reports_missing_members() -> None:
    modal = _modal("")
    assert "Add 2 more members" in modal._validation_text().plain


def test_validation_text_ready_when_valid() -> None:
    modal = _modal("claude/opus | codex/o3")
    assert "ready to confirm" in modal._validation_text().plain


# ---------------------------------------------------------------------------
# Add member
# ---------------------------------------------------------------------------


async def test_add_concrete_member_then_effort_appends_member() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("")
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._on_member_picked("opus")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        modal._on_member_effort_picked(DefaultEffortLevelChoice("medium"))
        await pilot.pause()
        assert modal._members == ["opus@medium"]


async def test_add_alias_member_rejects_selector_owning_alias() -> None:
    views = [
        make_alias_view("blogger", "user"),
        make_alias_view("pool_owner", "user", selector_mode="round_robin"),
    ]
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("", views=views)
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal.notify = MagicMock()  # type: ignore[method-assign]
        modal._on_member_picked("@pool_owner")
        await pilot.pause()
        assert modal._members == []
        modal.notify.assert_called_once()
        assert "reaches a pool" in modal.notify.call_args.args[0]


async def test_custom_member_without_effort_opens_effort_picker() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("")
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._on_member_picked(CUSTOM_SENTINEL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, CustomModelInputModal)
        modal._on_member_custom_picked("claude/sonnet")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        modal._on_member_effort_picked(DefaultEffortLevelChoice("high"))
        await pilot.pause()
        assert modal._members == ["claude/sonnet@high"]


async def test_custom_member_with_explicit_effort_skips_effort_picker() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("")
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._on_member_custom_picked("claude/sonnet@xhigh")
        await pilot.pause()
        assert modal._members == ["claude/sonnet@xhigh"]
        assert isinstance(pilot.app.screen, SelectorBuilderModal)


async def test_custom_member_rejects_unknown_alias() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("")
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal.notify = MagicMock()  # type: ignore[method-assign]
        modal._on_member_custom_picked("@totally_unknown")
        await pilot.pause()
        assert modal._members == []
        modal.notify.assert_called_once()
        assert "unknown alias" in modal.notify.call_args.args[0]


# ---------------------------------------------------------------------------
# Remove / reorder
# ---------------------------------------------------------------------------


async def test_remove_and_reorder_members() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("claude/opus | codex/o3 | claude/sonnet")
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one(f"#{modal._option_list_id}", OptionList)

        option_list.highlighted = 1
        modal.action_move_down()
        await pilot.pause()
        assert modal._members == ["claude/opus", "claude/sonnet", "codex/o3"]

        option_list.highlighted = 0
        modal.action_move_up()
        await pilot.pause()
        assert modal._members == ["claude/opus", "claude/sonnet", "codex/o3"]

        option_list.highlighted = 0
        modal.action_remove_member()
        await pilot.pause()
        assert modal._members == ["claude/sonnet", "codex/o3"]


# ---------------------------------------------------------------------------
# Mode toggle
# ---------------------------------------------------------------------------


async def test_toggle_mode_flips_between_pool_and_fallback() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("claude/opus | codex/o3")
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal.action_toggle_mode()
        await pilot.pause()
        assert modal._mode == "fallback"
        modal.action_toggle_mode()
        await pilot.pause()
        assert modal._mode == "round_robin"


# ---------------------------------------------------------------------------
# Per-member effort
# ---------------------------------------------------------------------------


async def test_edit_effort_sets_and_clears_member_effort() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = SelectorBuilderModal(
            alias="blogger",
            current_value="claude/opus | codex/o3",
            alias_context=make_alias_context(target="blogger"),
            effort_snapshot=EffectiveDefaultEffortSnapshot(None, None, 0.0),
            now=0.0,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one(f"#{modal._option_list_id}", OptionList)
        option_list.highlighted = 0

        modal.action_edit_effort()
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        modal._on_member_effort_edited(DefaultEffortLevelChoice("high"))
        await pilot.pause()
        assert modal._members[0] == "claude/opus@high"
        pilot.app.pop_screen()
        await pilot.pause()

        option_list.highlighted = 0
        modal.action_edit_effort()
        await pilot.pause()
        modal._on_member_effort_edited(DefaultEffortLevelChoice(None))
        await pilot.pause()
        assert modal._members[0] == "claude/opus"


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------


async def test_confirm_blocked_below_two_members() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("claude/opus")
        captured: list[str | None] = []
        pilot.app.push_screen(modal, captured.append)
        await pilot.pause()
        modal.action_confirm()
        await pilot.pause()
        assert isinstance(pilot.app.screen, SelectorBuilderModal)
        assert captured == []


async def test_confirm_emits_normalized_expression() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("claude/opus || codex/o3")
        captured: list[str | None] = []
        pilot.app.push_screen(modal, captured.append)
        await pilot.pause()
        modal.action_confirm()
        await pilot.pause()
        assert captured == ["claude/opus || codex/o3"]


async def test_confirm_blocked_on_validation_error() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = _modal("")
        captured: list[str | None] = []
        pilot.app.push_screen(modal, captured.append)
        await pilot.pause()
        modal._members = ["claude/opus", "@totally_unknown_alias"]
        modal.action_confirm()
        await pilot.pause()
        assert isinstance(pilot.app.screen, SelectorBuilderModal)
        assert captured == []
