"""Tests for the Models panel's persistent Reset action.

Phase 3 (epic sase-5e): covers the ``r`` (Reset) action on :class:`ModelsPanel`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel_edit as models_panel_edit
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_edit import AliasEditPreviewModal
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    highlight_row,
    make_alias_view,
    make_edit_plan,
    patch_alias_views,
)


async def test_action_reset_unconfigured_warns_and_skips(monkeypatch: Any) -> None:
    patch_alias_views(
        monkeypatch, [make_alias_view("medium", "role", configured=False)]
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "medium")
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel.action_reset()
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        assert panel.notify.call_args.kwargs.get("severity") == "warning"


async def test_action_reset_configured_opens_preview_with_unset(
    monkeypatch: Any,
) -> None:
    patch_alias_views(
        monkeypatch,
        [make_alias_view("medium", "role", configured=True, configured_value="opus")],
    )
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan(op="unset")
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "medium")
        panel.action_reset()
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.kind == "unset"


async def test_action_reset_custom_alias_deletes_custom_entry(
    monkeypatch: Any,
) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view(
                "blogger",
                "user",
                configured=True,
                configured_value="claude/opus",
                configured_source="custom",
            )
        ],
    )
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: make_edit_plan(op="unset")
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "blogger")
        panel.action_reset()
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._path == "llm_provider.model_aliases.custom.blogger"
        assert screen._reset_deletes_alias is True
