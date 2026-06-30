"""Tests for :mod:`sase.ace.tui.modals.models_panel` and its leader dispatch.

Phase 2 (epic sase-5e): the Models panel replaces the single-purpose temporary
override modal. Covers row rendering, the duration picker, the per-alias
set/change/clear flows, and the renamed ``,m`` leader action (plus its
back-compat with the old ``temporary_llm_override`` action id).
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

from textual.app import App, ComposeResult

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
from sase.ace.tui.modals.model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal
from sase.ace.tui.modals.models_panel import (
    ModelsPanel,
    ModelsPanelResult,
    _DurationPickerModal,
    _format_duration_chosen,
    _format_remaining,
    _kind_label,
    _state_tag,
    _render_alias_row,
)
from sase.ace.tui.widgets import LLMOverrideIndicator
from sase.llm_provider import AliasKind, AliasView, TemporaryLLMOverride
from tests._temporary_llm_override_helpers import full_registry


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _view(
    name: str,
    kind: AliasKind,
    *,
    configured: bool = False,
    configured_value: str | None = None,
    provider: str | None = "claude",
    model: str = "opus",
    override: TemporaryLLMOverride | None = None,
) -> AliasView:
    return AliasView(
        name=name,
        kind=kind,
        configured=configured,
        configured_value=configured_value,
        provider=provider,
        model=model,
        override=override,
    )


def _override(expires_at: float | None = 3600.0) -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=0.0,
        expires_at=expires_at,
        source="test",
    )


# ---------------------------------------------------------------------------
# Duration / formatting helpers
# ---------------------------------------------------------------------------


def test_format_remaining_hours_minutes() -> None:
    assert _format_remaining(3600 + 30 * 60) == "1h30m"


def test_format_remaining_seconds_when_subminute() -> None:
    assert _format_remaining(45) == "45s"


def test_format_remaining_clamps_negative() -> None:
    assert _format_remaining(-10) == "0s"


def test_format_duration_chosen_until_cleared() -> None:
    assert _format_duration_chosen(None) == "until cleared"


def test_format_duration_chosen_finite() -> None:
    assert _format_duration_chosen(90 * 60.0) == "1h30m"


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------


def test_kind_label_provider_coder_strips_suffix() -> None:
    view = _view("codex_coder", "provider_coder")
    assert _kind_label(view) == "codex coder"


def test_state_tag_configured() -> None:
    view = _view("myalias", "user", configured=True, configured_value="claude/opus")
    text, _ = _state_tag(view, now=0.0)
    assert text == "configured"


def test_state_tag_implicit_default() -> None:
    text, _ = _state_tag(_view("default", "default"), now=0.0)
    assert text == "implicit"


def test_state_tag_implicit_role() -> None:
    text, _ = _state_tag(_view("coder", "role"), now=0.0)
    assert text == "implicit → @default"


def test_state_tag_override_with_remaining() -> None:
    view = _view("coder", "role", override=_override(expires_at=3600.0))
    text, _ = _state_tag(view, now=0.0)
    assert text == "override · 1h left"


def test_state_tag_override_until_cleared() -> None:
    view = _view("coder", "role", override=_override(expires_at=None))
    text, _ = _state_tag(view, now=0.0)
    assert text == "override · until cleared"


def test_render_alias_row_contains_name_provider_and_state() -> None:
    view = _view("phase_worker", "role", provider="codex", model="o3")
    line = _render_alias_row(view, now=0.0).plain
    assert "phase_worker" in line
    assert "CODEX(o3)" in line
    assert "implicit → @default" in line


# ---------------------------------------------------------------------------
# Duration picker presets
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


# ---------------------------------------------------------------------------
# Panel actions — no-mount unit coverage
# ---------------------------------------------------------------------------


def test_action_close_dismisses_unchanged() -> None:
    panel = ModelsPanel()
    panel.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    panel.action_close()
    (arg,), _ = panel.dismiss.call_args
    assert isinstance(arg, ModelsPanelResult)
    assert arg.changed is False


def test_on_duration_picked_cancel_is_noop(monkeypatch) -> None:
    panel = ModelsPanel()
    panel._refresh_rows = MagicMock()  # type: ignore[method-assign]
    set_mock = MagicMock()
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)
    panel._on_duration_picked(models_panel.DURATION_CHOICE_CANCELLED)
    set_mock.assert_not_called()
    assert panel._changed is False


def test_on_duration_picked_invalid_notifies_error(monkeypatch) -> None:
    panel = ModelsPanel()
    panel.notify = MagicMock()  # type: ignore[method-assign]
    panel._refresh_rows = MagicMock()  # type: ignore[method-assign]
    panel._pending_alias = "coder"
    panel._pending_raw_model = "bad"
    monkeypatch.setattr(
        models_panel,
        "set_alias_override",
        MagicMock(side_effect=ValueError("nope")),
    )
    panel._on_duration_picked(60.0)
    assert panel._changed is False
    panel.notify.assert_called_once()
    assert panel.notify.call_args.kwargs.get("severity") == "error"


# ---------------------------------------------------------------------------
# Panel interaction — pilot flows
# ---------------------------------------------------------------------------


def _patch_views(monkeypatch, views: list[AliasView]) -> None:
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: views)
    monkeypatch.setattr(models_panel, "_now", lambda: 0.0)


async def test_panel_escape_closes_unchanged(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("default", "default")])
    result: ModelsPanelResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: ModelsPanelResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(ModelsPanel(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert isinstance(result, ModelsPanelResult)
    assert result.changed is False


async def test_panel_o_opens_model_picker(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)


async def test_panel_x_clears_active_override(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("phase_worker", "role", override=_override())])
    clear_mock = MagicMock(return_value=True)
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)
    result: ModelsPanelResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: ModelsPanelResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(ModelsPanel(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    clear_mock.assert_called_once_with("phase_worker")
    assert isinstance(result, ModelsPanelResult)
    assert result.changed is True


async def test_panel_x_without_override_does_not_clear(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role", override=None)])
    clear_mock = MagicMock()
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        clear_mock.assert_not_called()
        assert panel._changed is False


async def test_set_flow_threads_model_and_duration(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    fake = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="o3",
        created_at=0.0,
        expires_at=3600.0,
        source="ace",
    )
    set_mock = MagicMock(return_value=fake)
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._on_model_picked("o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        panel._on_duration_picked(3600.0)
        await pilot.pause()

    set_mock.assert_called_once_with("coder", "o3", 3600.0, source="ace")
    assert panel._changed is True


async def test_custom_model_path_opens_input_then_duration(monkeypatch) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._on_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, CustomModelInputModal)
        panel._on_custom_picked("codex/o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        assert panel._pending_raw_model == "codex/o3"


# ---------------------------------------------------------------------------
# Leader-mode dispatch
# ---------------------------------------------------------------------------


def test_leader_handler_dispatches_models_panel() -> None:
    mixin = MagicMock()
    mixin._keymap_registry = full_registry()
    mixin.current_tab = "changespecs"
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "m")

    assert handled is True
    mixin._open_models_panel.assert_called_once()


def test_leader_handler_honors_legacy_action_id() -> None:
    """A user keymap still binding the old action id keeps opening the panel."""
    mixin = MagicMock()
    mixin._keymap_registry = full_registry(
        {
            "keymaps": {
                "modes": {"leader_mode": {"keys": {"temporary_llm_override": "z"}}}
            }
        }
    )
    mixin.current_tab = "changespecs"
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "z")

    assert handled is True
    mixin._open_models_panel.assert_called_once()


def test_open_models_panel_refreshes_indicator_when_changed() -> None:
    mixin = MagicMock()
    indicator = MagicMock(spec=LLMOverrideIndicator)
    mixin.query_one.return_value = indicator

    LeaderModeMixin._open_models_panel(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(ModelsPanelResult(changed=True))

    mixin.query_one.assert_called_once_with(
        "#llm-override-indicator", LLMOverrideIndicator
    )
    indicator.refresh.assert_called_once()


def test_open_models_panel_no_refresh_when_unchanged() -> None:
    mixin = MagicMock()

    LeaderModeMixin._open_models_panel(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(ModelsPanelResult(changed=False))

    mixin.query_one.assert_not_called()
