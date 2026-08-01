"""Shared fixtures for Config Center Config pane widget tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.config.inventory import build_config_inventory, config_field_model
from tests.test_config_pane import _fixture_layers, _fixture_schema


def _fixture_view() -> cp.ConfigPaneView:
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=_fixture_layers(),
    ):
        inventory = build_config_inventory(schema=_fixture_schema())
    field_model = config_field_model(_fixture_schema())
    return cp.ConfigPaneView.build(field_model, inventory)


def _patch_loaders(
    monkeypatch: pytest.MonkeyPatch, view: cp.ConfigPaneView | None = None
) -> cp.ConfigPaneView:
    view = view or _fixture_view()
    result = cp._LoadResult(view=view, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: result)
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: None)
    # Keep the XPrompts pane cheap and deterministic.
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    # Keep the Projects pane cheap and deterministic.
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )
    return view


async def _open_config_pane(
    page: AcePage,
    *,
    session_state: AdminCenterSessionState | None = None,
) -> ConfigPane:
    modal = ConfigCenterModal(initial_tab="config", session_state=session_state)
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    pane = modal.query_one("#config", ConfigPane)
    await page.wait_for(lambda _s: bool(pane._node_by_path))
    return pane
