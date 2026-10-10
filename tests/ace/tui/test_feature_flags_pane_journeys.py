"""App-level Config Flags pane journeys over the real mutation facade."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from textual.css.query import NoMatches

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_catalog import config_panel_tabs
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import (
    ConfigHubEntry,
    config_subtab_order,
)
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.feature_flags_pane import FeatureFlagsPane
from sase.feature_flags import FeatureFlag, current_flags, override_flags
from sase.feature_flags import snapshot as snapshot_mod
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV, parse_feature_flags_env
from sase.feature_flags.state import (
    feature_flag_state_path,
    load_saved_feature_flags,
)
from tests._conftest_runtime import reset_process_feature_flags
from tests.feature_flags._helpers import demo_flag

KEY = "demo_sunset_flag"
ROLLOUT = "admin_center_flags"


def _install_synthetic_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add a synthetic sunset flag alongside the live registry.

    Generic toggle coverage addresses only this key, so later
    flag-retirement phases can delete production keys without breaking
    these journeys. The live registry stays because the booted TUI still
    consumes production flags (owned by their own retirement phases).
    """
    from sase.feature_flags.registry import feature_flag_definitions

    test_definitions = dict(feature_flag_definitions())
    test_definitions[KEY] = demo_flag(KEY, kind="sunset")
    monkeypatch.setattr(
        "sase.feature_flags.registry.feature_flag_definitions",
        lambda: test_definitions,
    )
    monkeypatch.setattr(
        snapshot_mod, "feature_flag_definitions", lambda: test_definitions
    )
    # NOTE: ``cli_views`` holds its own direct registry import, which the
    # Flags pane uses to build rows; patch it too or the synthetic flag
    # never appears in the pane.
    monkeypatch.setattr(
        "sase.feature_flags.cli_views.feature_flag_definitions",
        lambda: test_definitions,
    )
    reset_process_feature_flags()


@pytest.fixture(autouse=True)
def _clean_flag_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    reset_process_feature_flags()
    yield
    reset_process_feature_flags()


async def _open_flags_pane(
    page: AcePage,
) -> tuple[ConfigCenterModal, FeatureFlagsPane]:
    modal = ConfigCenterModal(config_entry=ConfigHubEntry(subtab="flags"))
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    hub = modal.query_one("#config", ConfigHubPane)
    await page.wait_for(lambda _s: hub._active_subtab == "flags")
    await page.wait_for(lambda _s: bool(modal.query("#flags")))
    pane = modal.query_one("#flags", FeatureFlagsPane)
    await page.wait_for(lambda _s: not pane._loading and bool(pane._views))
    return modal, pane


def _select_flag(pane: FeatureFlagsPane, key: str) -> None:
    idx = next(
        index
        for index, view in enumerate(pane._views)
        if str(view.definition.key) == key
    )
    pane._flag_list().highlighted = idx


async def test_flags_pane_enable_and_disable_write_state_and_request_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_flag(monkeypatch)
    restarts: list[bool] = []
    async with AcePage(initial_tab="agents") as page:
        page.app._restart_tui = (  # type: ignore[method-assign]
            lambda *, restart_axe: restarts.append(restart_axe)
        )
        _modal, pane = await _open_flags_pane(page)
        _select_flag(pane, KEY)
        await page.pause()
        selected = pane._selected_view()
        assert pane._current_key == KEY
        assert selected is not None
        assert selected.decision.enabled is True

        pane.action_toggle_flag()
        await page.expect_modal("ConfirmActionModal")
        await page.press("y")
        await page.wait_for(lambda _s: restarts == [True])

        loaded = load_saved_feature_flags()
        assert loaded.flags[KEY] is False
        raw = json.loads(Path(feature_flag_state_path()).read_text(encoding="utf-8"))
        assert raw["flags"][KEY] is False
        assert current_flags().enabled(KEY) is False
        assert parse_feature_flags_env(os.environ[SASE_FEATURE_FLAGS_ENV])[KEY] is False
        assert restarts == [True]

        os.environ.pop(SASE_FEATURE_FLAGS_ENV, None)
        reset_process_feature_flags()
        saved_decision = current_flags().decision(KEY)
        assert saved_decision.enabled is False
        assert saved_decision.source == "state"


async def test_disabling_rollout_flag_omits_flags_from_post_restart_catalog() -> None:
    restarts: list[bool] = []
    async with AcePage(initial_tab="agents") as page:
        page.app._restart_tui = (  # type: ignore[method-assign]
            lambda *, restart_axe: restarts.append(restart_axe)
        )
        _modal, pane = await _open_flags_pane(page)
        _select_flag(pane, ROLLOUT)
        await page.pause()
        pane.action_toggle_flag()
        await page.expect_modal("ConfirmActionModal")
        confirm = page.app.screen
        assert isinstance(confirm, ConfirmActionModal)
        assert "sase flag enable admin_center_flags" in (confirm._subject or "")
        await page.press("y")
        await page.wait_for(lambda _s: restarts == [True])

        assert load_saved_feature_flags().flags[ROLLOUT] is False
        assert current_flags().enabled(FeatureFlag.admin_center_flags) is False
        assert "flags" not in config_subtab_order()
        assert tuple(tab.id for tab in config_panel_tabs()) == (
            "misc",
            "holds",
            "launch",
            "memory",
            "snippets",
            "macros",
        )

        fresh = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(fresh)
        await page.wait_for(lambda _s: bool(fresh.query("#config")))
        hub = fresh.query_one("#config", ConfigHubPane)
        await page.wait_for(lambda _s: bool(hub._subtab_order))
        assert "flags" not in hub._subtab_order
        with pytest.raises(NoMatches):
            hub.query_one("#flags", FeatureFlagsPane)


async def test_config_catalog_omits_flags_when_rollout_is_off() -> None:
    with override_flags(admin_center_flags=False):
        async with AcePage(initial_tab="agents") as page:
            modal = ConfigCenterModal(initial_tab="config")
            page.app.push_screen(modal)
            await page.expect_modal("ConfigCenterModal")
            await page.wait_for(lambda _s: bool(modal.query("#config")))
            hub = modal.query_one("#config", ConfigHubPane)
            await page.wait_for(lambda _s: bool(hub._subtab_order))
            assert hub._active_subtab != "flags"
            assert "flags" not in hub._subtab_order
            assert tuple(tab.shortcut for tab in config_panel_tabs()) == (
                "01",
                "02",
                "03",
                "04",
                "05",
                "06",
            )


async def test_toggle_commits_saved_state_before_restart_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_flag(monkeypatch)
    restarts: list[bool] = []

    def capture(*, restart_axe: bool) -> None:
        assert load_saved_feature_flags().flags[KEY] is False
        restarts.append(restart_axe)

    async with AcePage(initial_tab="agents") as page:
        page.app._restart_tui = capture  # type: ignore[method-assign]
        _modal, pane = await _open_flags_pane(page)
        _select_flag(pane, KEY)
        await page.pause()
        pane.action_toggle_flag()
        await page.expect_modal("ConfirmActionModal")
        await page.press("y")
        await page.wait_for(lambda _s: restarts == [True])
        assert load_saved_feature_flags().flags[KEY] is False
