"""Tests for the Models panel's persistent Edit entry points.

Phase 3 (epic sase-5e): covers the ``e`` (Edit) action on :class:`ModelsPanel`
and the model-picker / selector-builder / effort-picker routing.
"""

from __future__ import annotations

from typing import Any

import sase.ace.tui.modals.models_panel_edit as models_panel_edit
from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    SELECTOR_SENTINEL,
    AliasSelectionContext,
    ModelPickerModal,
)
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_edit import AliasEditPreviewModal
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
)
from sase.ace.tui.modals.models_panel_selector_builder import SelectorBuilderModal
from sase.llm_provider import TemporaryProviderDisable
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    highlight_row,
    make_alias_view,
    make_edit_plan,
    patch_alias_views,
    wait_for,
)


def _disable(provider: str) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=None,
        source="test",
    )


async def test_action_edit_opens_model_picker(monkeypatch: Any) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium", "role")])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await wait_for(pilot, lambda: "medium" in panel._row_by_id)
        highlight_row(panel, "medium")
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)


async def test_action_edit_picker_uses_flat_alias_snapshot(monkeypatch: Any) -> None:
    views = [
        make_alias_view("medium", "role"),
        make_alias_view(
            "bucketed_a",
            "user",
            configured=True,
            configured_value="claude/opus",
            configured_source="custom",
        ),
        make_alias_view(
            "bucketed_b",
            "user",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
            configured_source="custom",
        ),
    ]
    patch_alias_views(monkeypatch, views)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        disable = _disable("codex")
        panel._provider_disables = {"codex": disable}
        highlight_row(panel, "medium")
        await pilot.press("e")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        assert picker._alias_context is not None
        assert picker._alias_context.views == tuple(views)
        assert picker._provider_disables == {"codex": disable}
        ids = {row.option_id for row in picker._all_rows}
        assert {"@bucketed_a", "@bucketed_b"} <= ids


async def test_action_edit_picker_offers_selector_builder_row(monkeypatch: Any) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "medium")
        await pilot.press("e")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        assert any(row.option_id == SELECTOR_SENTINEL for row in picker._all_rows)


async def test_on_edit_model_picked_selector_sentinel_opens_builder(
    monkeypatch: Any,
) -> None:
    target = make_alias_view("medium", "role")
    other = make_alias_view("xlarge", "role")
    patch_alias_views(monkeypatch, [target, other])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = target
        panel._pending_alias_selection = AliasSelectionContext(
            (target, other), target.name, "persistent"
        )
        panel._on_edit_model_picked(SELECTOR_SENTINEL)
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, SelectorBuilderModal)
        assert screen._alias == "medium"
        assert screen._provider_disables == panel._provider_disables


async def test_on_selector_built_routes_to_preview(monkeypatch: Any) -> None:
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
        panel._on_selector_built("claude/opus | codex/o3")
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "claude/opus | codex/o3"
        assert panel._pending_edit_raw_model == "claude/opus | codex/o3"


async def test_on_selector_built_cancel_is_noop(monkeypatch: Any) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._on_selector_built(None)
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)


async def test_on_edit_model_picked_opens_preview_with_set_op(monkeypatch: Any) -> None:
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
    target = make_alias_view("large", "role")
    medium = make_alias_view("medium", "role", provider="codex", model="o3")
    patch_alias_views(monkeypatch, [target, medium])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = target
        panel._pending_alias_selection = AliasSelectionContext(
            (target, medium), target.name, "persistent"
        )
        panel._on_edit_model_picked("@medium")
        await pilot.pause()

        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice("xhigh"))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@medium@xhigh"


async def test_on_edit_model_picked_custom_then_preview(monkeypatch: Any) -> None:
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
        panel._on_edit_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, CustomModelInputModal)
        panel._on_edit_custom_picked("@large")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice("medium"))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@large@medium"


async def test_on_edit_model_picked_cancel_is_noop(monkeypatch: Any) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._on_edit_model_picked(None)
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)


async def test_on_edit_effort_cancel_does_not_open_preview(
    monkeypatch: Any,
) -> None:
    view = make_alias_view("medium", "role")
    patch_alias_views(monkeypatch, [view])

    async with ModelsPanelTestApp().run_test() as pilot:
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


async def test_action_edit_custom_alias_routes_to_custom_model_path(
    monkeypatch: Any,
) -> None:
    view = make_alias_view(
        "blogger",
        "user",
        configured=True,
        configured_value="claude/haiku",
        configured_source="custom",
    )
    patch_alias_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan()
    )

    async with ModelsPanelTestApp().run_test() as pilot:
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
