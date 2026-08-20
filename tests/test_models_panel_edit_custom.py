"""Tests for Models panel custom-model input during persistent Edit.

Phase 3 (epic sase-5e): covers custom-value validation, prefill, and the
preview routing that starts from :class:`CustomModelInputModal`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel_edit as models_panel_edit
from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    AliasSelectionContext,
)
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_edit import AliasEditPreviewModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.llm_provider import TemporaryProviderDisable
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    make_edit_plan,
    patch_alias_views,
)


def _disable(provider: str) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=None,
        source="test",
    )


async def test_on_edit_custom_rejects_unknown_and_cyclic_aliases(
    monkeypatch: Any,
) -> None:
    target = make_alias_view("medium", "role")
    dependent = make_alias_view(
        "dependent",
        "user",
        configured=True,
        configured_value="@medium",
    )
    patch_alias_views(monkeypatch, [target, dependent])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = target
        panel._pending_alias_selection = AliasSelectionContext(
            (target, dependent), target.name, "persistent"
        )

        panel._on_edit_custom_picked("@missing")
        panel._on_edit_custom_picked("@dependent@medium")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        assert panel.notify.call_count == 2
        messages = [call.args[0] for call in panel.notify.call_args_list]
        assert "unknown alias" in messages[0]
        assert "would create a cycle" in messages[1]


async def test_on_edit_custom_rejects_disabled_explicit_provider_before_preview(
    monkeypatch: Any,
) -> None:
    view = make_alias_view("medium", "role")
    patch_alias_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = view
        panel._provider_disables = {"claude": _disable("claude")}

        panel._on_edit_custom_picked("claude/opus@medium")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        assert panel._pending_edit_raw_model == ""
        panel.notify.assert_called_once()
        message = panel.notify.call_args.args[0]
        assert "Cannot set @medium to claude/opus@medium" in message
        assert "CLAUDE is temporarily disabled until cleared" in message


async def test_on_edit_custom_allows_soft_disabled_explicit_provider(
    monkeypatch: Any,
) -> None:
    view = make_alias_view("medium", "role")
    patch_alias_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )
    disable = TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider="claude",
        created_at=100.0,
        expires_at=None,
        source="test",
        mode="soft",
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = view
        panel._provider_disables = {"claude": disable}

        panel._on_edit_custom_picked("claude/opus@medium")
        await pilot.pause()

        assert isinstance(pilot.app.screen, AliasEditPreviewModal)
        assert panel._pending_edit_raw_model == "claude/opus@medium"
        panel.notify.assert_called_once()
        assert "CLAUDE is soft-disabled until cleared" in panel.notify.call_args.args[0]


async def test_on_edit_custom_accepts_fallback_and_rejects_mixed_selector(
    monkeypatch: Any,
) -> None:
    view = make_alias_view("xlarge", "role")
    patch_alias_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = view

        panel._on_edit_custom_picked(
            "claude/claude-fable-5@low || codex/gpt-5.6-sol@high"
        )
        await pilot.pause()
        assert isinstance(pilot.app.screen, AliasEditPreviewModal)
        assert pilot.app.screen._op.value == (
            "claude/claude-fable-5@low || codex/gpt-5.6-sol@high"
        )

        pilot.app.pop_screen()
        await pilot.pause()
        panel._on_edit_custom_picked("claude/opus | codex/o3 || claude/sonnet")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)
        assert "cannot mix" in panel.notify.call_args.args[0]

        panel._on_edit_custom_picked("(claude/opus | codex/o3) || grok/grok-4.6@xhigh")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AliasEditPreviewModal)
        assert pilot.app.screen._op.value == (
            "(claude/opus | codex/o3) || grok/grok-4.6@xhigh"
        )


async def test_on_edit_custom_preserves_alias_selector_member_efforts(
    monkeypatch: Any,
) -> None:
    view = make_alias_view(
        "blogger",
        "user",
        configured=True,
        configured_source="custom",
    )
    patch_alias_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.models_panel_alias_edit."
        "validate_model_alias_selector_value",
        lambda *a, **k: (),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        value = "@large@low | @medium@high"
        panel._on_edit_custom_picked(value)
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == value
        assert panel._pending_edit_raw_model == value


async def test_on_edit_custom_rejects_pool_member_unknown_alias_before_preview(
    monkeypatch: Any,
) -> None:
    target = make_alias_view("medium", "role")
    patch_alias_views(monkeypatch, [target])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = target
        panel._pending_alias_selection = AliasSelectionContext(
            (target,), target.name, "persistent"
        )

        panel._on_edit_custom_picked("@missing | claude/opus")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        assert "unknown alias" in panel.notify.call_args.args[0]


async def test_on_edit_custom_rejects_disabled_selector_member_before_preview(
    monkeypatch: Any,
) -> None:
    target = make_alias_view("medium", "role")
    patch_alias_views(monkeypatch, [target])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = target
        panel._provider_disables = {"codex": _disable("codex")}

        panel._on_edit_custom_picked("claude/opus | codex/o3")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        assert panel._pending_edit_raw_model == ""
        panel.notify.assert_called_once()
        message = panel.notify.call_args.args[0]
        assert "Cannot set @medium to codex/o3" in message
        assert "CODEX is temporarily disabled until cleared" in message


async def test_on_edit_custom_rejects_pool_member_cycle_before_preview(
    monkeypatch: Any,
) -> None:
    target = make_alias_view("medium", "role")
    dependent = make_alias_view(
        "dependent",
        "user",
        configured=True,
        configured_value="@medium",
    )
    patch_alias_views(monkeypatch, [target, dependent])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = target
        panel._pending_alias_selection = AliasSelectionContext(
            (target, dependent), target.name, "persistent"
        )

        panel._on_edit_custom_picked("@dependent | claude/opus")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        assert "would create a cycle" in panel.notify.call_args.args[0]


async def test_on_edit_custom_opens_prefilled_with_configured_value(
    monkeypatch: Any,
) -> None:
    view = make_alias_view(
        "blogger",
        "user",
        configured=True,
        configured_value="claude/opus | codex/o3",
        configured_source="custom",
    )
    patch_alias_views(monkeypatch, [view])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, CustomModelInputModal)
        input_widget = screen.query_one("#custom-model-input", SingleLineVimTextArea)
        assert input_widget.text == "claude/opus | codex/o3"
        assert input_widget.cursor_location == input_widget.document.end


async def test_on_edit_custom_opens_empty_when_alias_has_no_value(
    monkeypatch: Any,
) -> None:
    view = make_alias_view("medium", "role")
    patch_alias_views(monkeypatch, [view])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, CustomModelInputModal)
        input_widget = screen.query_one("#custom-model-input", SingleLineVimTextArea)
        assert input_widget.text == ""
        assert input_widget.placeholder == "e.g. claude/fable || codex/gpt-5.6-sol"


async def test_on_edit_custom_explicit_alias_effort_skips_effort_picker(
    monkeypatch: Any,
) -> None:
    view = make_alias_view("medium", "role")
    patch_alias_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_custom_picked("@large@medium")
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@large@medium"
