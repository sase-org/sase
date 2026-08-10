"""Tests for the Models panel's persistent Edit/Reset interactions.

Phase 3 (epic sase-5e): covers the ``e`` (Edit) / ``r`` (Reset) actions on
:class:`ModelsPanel` and the model-picker / custom-input entry points.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel_edit as models_panel_edit
from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    AliasSelectionContext,
    ModelPickerModal,
)
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_edit import AliasEditPreviewModal
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
)
from tests._models_panel_helpers import (
    ModelsPanelTestApp as _TestApp,
    make_alias_view as _view,
    make_edit_plan as _make_plan,
    patch_alias_views as _patch_views,
)


# ---------------------------------------------------------------------------
# Panel — Edit entry points
# ---------------------------------------------------------------------------


async def test_action_edit_opens_model_picker(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("medium_worker", "role")])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("l", "e")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)


async def test_action_edit_picker_uses_flat_alias_snapshot(monkeypatch: Any) -> None:
    views = [
        _view("medium_worker", "role"),
        _view(
            "bucketed_a",
            "user",
            configured=True,
            configured_value="claude/opus",
            configured_source="custom",
        ),
        _view(
            "bucketed_b",
            "user",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
            configured_source="custom",
        ),
    ]
    _patch_views(monkeypatch, views)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("l", "e")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        assert picker._alias_context is not None
        assert picker._alias_context.views == tuple(views)
        ids = {row.option_id for row in picker._all_rows}
        assert {"@bucketed_a", "@bucketed_b"} <= ids


async def test_on_edit_model_picked_opens_preview_with_set_op(monkeypatch: Any) -> None:
    view = _view("medium_worker", "role")
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked("opus")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice("medium"))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.kind == "set"
        assert screen._op.value == "opus@medium"


async def test_on_edit_alias_picked_persists_raw_reference(monkeypatch: Any) -> None:
    target = _view("big_epic_lander", "role")
    medium_worker = _view("medium_worker", "role", provider="codex", model="o3")
    _patch_views(monkeypatch, [target, medium_worker])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = target
        panel._pending_alias_selection = AliasSelectionContext(
            (target, medium_worker), target.name, "persistent"
        )
        panel._on_edit_model_picked("@medium_worker")
        await pilot.pause()

        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice("xhigh"))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@medium_worker@xhigh"


async def test_on_edit_model_picked_custom_then_preview(monkeypatch: Any) -> None:
    view = _view("medium_worker", "role")
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, CustomModelInputModal)
        panel._on_edit_custom_picked("@default")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice("medium"))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@default@medium"


async def test_on_edit_custom_rejects_unknown_and_cyclic_aliases(
    monkeypatch: Any,
) -> None:
    target = _view("medium_worker", "role")
    dependent = _view(
        "dependent",
        "user",
        configured=True,
        configured_value="@medium_worker",
    )
    _patch_views(monkeypatch, [target, dependent])

    async with _TestApp().run_test() as pilot:
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


async def test_on_edit_custom_accepts_fallback_and_rejects_mixed_selector(
    monkeypatch: Any,
) -> None:
    view = _view("smartest", "role")
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
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


async def test_on_edit_custom_preserves_alias_selector_member_efforts(
    monkeypatch: Any,
) -> None:
    view = _view(
        "blogger",
        "user",
        configured=True,
        configured_source="custom",
    )
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.models_panel_alias_edit."
        "validate_model_alias_selector_value",
        lambda *a, **k: (),
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        value = "@default@low | @medium_worker@high"
        panel._on_edit_custom_picked(value)
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == value
        assert panel._pending_edit_raw_model == value


async def test_on_edit_model_picked_cancel_is_noop(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("medium_worker", "role")])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._on_edit_model_picked(None)
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)


async def test_on_edit_custom_explicit_alias_effort_skips_effort_picker(
    monkeypatch: Any,
) -> None:
    view = _view("medium_worker", "role")
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_custom_picked("@default@medium")
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@default@medium"


async def test_on_edit_effort_cancel_does_not_open_preview(
    monkeypatch: Any,
) -> None:
    view = _view("medium_worker", "role")
    _patch_views(monkeypatch, [view])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked("opus")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(None)
        await pilot.pause()

        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)


# ---------------------------------------------------------------------------
# Panel — Reset
# ---------------------------------------------------------------------------


async def test_action_reset_unconfigured_warns_and_skips(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("medium_worker", "role", configured=False)])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("l")
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel.action_reset()
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        assert panel.notify.call_args.kwargs.get("severity") == "warning"


async def test_action_reset_configured_opens_preview_with_unset(
    monkeypatch: Any,
) -> None:
    _patch_views(
        monkeypatch,
        [_view("medium_worker", "role", configured=True, configured_value="opus")],
    )
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan(op="unset")
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("l")
        panel.action_reset()
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.kind == "unset"


async def test_action_edit_custom_alias_routes_to_custom_model_path(
    monkeypatch: Any,
) -> None:
    view = _view(
        "blogger",
        "user",
        configured=True,
        configured_value="claude/haiku",
        configured_source="custom",
    )
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked("claude/opus")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice(None))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._path == "llm_provider.model_aliases.custom.blogger.model"


async def test_action_reset_custom_alias_deletes_custom_entry(
    monkeypatch: Any,
) -> None:
    _patch_views(
        monkeypatch,
        [
            _view(
                "blogger",
                "user",
                configured=True,
                configured_value="claude/opus",
                configured_source="custom",
            )
        ],
    )
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan(op="unset")
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("j")
        panel.action_reset()
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._path == "llm_provider.model_aliases.custom.blogger"
        assert screen._reset_deletes_alias is True
