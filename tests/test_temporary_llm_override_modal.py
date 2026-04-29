"""Tests for :mod:`sase.ace.tui.modals.temporary_llm_override_modal`.

Phase-3 work.  Phase-1 covers the underlying state primitive and Phase-2
covers provider-resolution wiring; this module just verifies the modal
itself plus the leader-key dispatch in :class:`LeaderModeMixin`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from textual.app import App, ComposeResult

from sase.ace.tui.keymaps.types import LeaderModeKeymaps
from sase.ace.tui.modals.temporary_llm_override_modal import (
    TemporaryLLMOverrideModal,
    TemporaryOverrideResult,
    _DurationPickerModal,
    _format_duration_chosen,
    _format_remaining,
)
from sase.llm_provider.temporary_override import (
    get_active_temporary_override,
    set_temporary_override,
)


# ---------------------------------------------------------------------------
# Default leader keymap exposes the new chord
# ---------------------------------------------------------------------------


def test_leader_default_includes_temporary_llm_override() -> None:
    """The new ``,P`` chord ships in the typed leader-mode defaults."""
    leader = LeaderModeKeymaps()
    assert leader.keys["temporary_llm_override"] == "P"


def test_leader_default_in_yaml() -> None:
    """``default_config.yml`` and the typed defaults agree on the chord."""
    import importlib.resources

    import yaml  # type: ignore[import-untyped]

    text = (
        importlib.resources.files("sase")
        .joinpath("default_config.yml")
        .read_text(encoding="utf-8")
    )
    data = yaml.safe_load(text)
    leader = data["ace"]["keymaps"]["modes"]["leader_mode"]["keys"]
    assert leader["temporary_llm_override"] == "P"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_format_remaining_hours_minutes() -> None:
    assert _format_remaining(3600 + 30 * 60) == "1h30m"


def test_format_remaining_minutes_only() -> None:
    assert _format_remaining(15 * 60) == "15m"


def test_format_remaining_seconds_when_subminute() -> None:
    assert _format_remaining(45) == "45s"


def test_format_remaining_clamps_negative_to_zero() -> None:
    assert _format_remaining(-10) == "0s"


def test_format_duration_chosen_until_cleared() -> None:
    assert _format_duration_chosen(None) == "until cleared"


def test_format_duration_chosen_finite() -> None:
    assert _format_duration_chosen(60.0 * 90) == "1h30m"


# ---------------------------------------------------------------------------
# Top-level modal — synchronous action methods
# ---------------------------------------------------------------------------


def _make_top_modal() -> TemporaryLLMOverrideModal:
    modal = TemporaryLLMOverrideModal()
    modal.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    return modal


def test_action_cancel_dismisses_with_cancelled() -> None:
    modal = _make_top_modal()
    modal.action_cancel()
    modal.dismiss.assert_called_once()
    (arg,), _ = modal.dismiss.call_args
    assert isinstance(arg, TemporaryOverrideResult)
    assert arg.action == "cancelled"
    assert arg.override is None


def test_action_clear_with_no_active_dismisses_cancelled() -> None:
    modal = _make_top_modal()
    assert modal._active is None
    modal.action_clear()
    (arg,), _ = modal.dismiss.call_args
    assert arg.action == "cancelled"


def test_action_clear_with_active_clears_state_and_dismisses_cleared() -> None:
    set_temporary_override("codex/o3", 3600.0, source="test")
    assert get_active_temporary_override() is not None

    modal = _make_top_modal()
    assert modal._active is not None
    modal.action_clear()

    assert get_active_temporary_override() is None
    (arg,), _ = modal.dismiss.call_args
    assert arg.action == "cleared"
    assert arg.override is None


def test_render_state_line_active() -> None:
    set_temporary_override("codex/o3", 3600.0, source="test")
    modal = TemporaryLLMOverrideModal()
    line = modal._render_state_line()
    assert "Active" in line
    assert "CODEX" in line
    assert "expires in" in line


def test_render_state_line_inactive_shows_default() -> None:
    modal = TemporaryLLMOverrideModal()
    line = modal._render_state_line()
    assert "Default" in line


def test_render_action_lines_active_shows_change_and_clear() -> None:
    set_temporary_override("codex/o3", 3600.0, source="test")
    modal = TemporaryLLMOverrideModal()
    lines = modal._render_action_lines()
    assert any("Change" in line for line in lines)
    assert any("Clear" in line for line in lines)


def test_render_action_lines_inactive_shows_set_only() -> None:
    modal = TemporaryLLMOverrideModal()
    lines = modal._render_action_lines()
    assert len(lines) == 1
    assert "Set override" in lines[0]


# ---------------------------------------------------------------------------
# Duration picker modal — synchronous preset dispatch
# ---------------------------------------------------------------------------


def _make_duration_modal() -> _DurationPickerModal:
    modal = _DurationPickerModal()
    modal.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    return modal


def test_duration_preset_1_returns_15m() -> None:
    modal = _make_duration_modal()
    modal.action_preset_1()
    modal.dismiss.assert_called_once_with(15 * 60.0)


def test_duration_preset_3_returns_1h() -> None:
    modal = _make_duration_modal()
    modal.action_preset_3()
    modal.dismiss.assert_called_once_with(60 * 60.0)


def test_duration_preset_6_until_cleared_returns_none() -> None:
    modal = _make_duration_modal()
    modal.action_preset_6()
    modal.dismiss.assert_called_once_with(None)


async def test_duration_cancel_dismisses_with_cancel_sentinel() -> None:
    """Cancel emits ``"__cancel__"`` so we can distinguish it from
    the legitimate ``None`` "until cleared" return."""
    result: float | None | str = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: float | None | str) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_DurationPickerModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert result == "__cancel__"


# ---------------------------------------------------------------------------
# End-to-end pilot tests
# ---------------------------------------------------------------------------


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_top_modal_escape_cancels() -> None:
    result: TemporaryOverrideResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(TemporaryLLMOverrideModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert result is not None
    assert result.action == "cancelled"


async def test_top_modal_x_clears_when_active() -> None:
    set_temporary_override("codex/o3", 3600.0, source="test")
    result: TemporaryOverrideResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(TemporaryLLMOverrideModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()

    assert result is not None
    assert result.action == "cleared"
    assert get_active_temporary_override() is None


async def test_duration_modal_preset_dismisses() -> None:
    result: float | None | str = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: float | None | str) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_DurationPickerModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()

    assert result == 60 * 60.0
