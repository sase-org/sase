"""ACE TUI PNG snapshots for Config Center Launch states."""

from __future__ import annotations

from collections.abc import Callable

import pytest

import sase.ace.tui.modals.models_panel as models_panel
import sase.ace.tui.modals.models_panel_providers as models_panel_providers
import sase.ace.tui.modals.models_panel_provider_state as models_panel_provider_state
from sase.ace.testing import AcePage
from sase.ace.tui.modals import LaunchPane
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.llm_provider import AliasView
from textual.widgets import OptionList
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    calm_views,
    provider_disable,
    provider_disabled_views,
    provider_status,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_alias_views(
    monkeypatch: pytest.MonkeyPatch, factory: Callable[[], list[AliasView]]
) -> None:
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: factory())
    monkeypatch.setattr(
        models_panel_provider_state, "build_alias_views", lambda *a, **k: factory()
    )


def _highlight_launch_row(pane: LaunchPane, row_id: str) -> None:
    option_list = pane.query_one("#models-panel-list", OptionList)
    pane._set_highlighted_index(option_list, option_list.get_option_index(row_id))
    pane._update_context()


async def _open_config_launch(page: AcePage) -> tuple[ConfigCenterModal, LaunchPane]:
    modal = ConfigCenterModal(config_entry=ConfigHubEntry(subtab="launch"))
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    hub = modal.query_one("#config", ConfigHubPane)
    await page.wait_for(lambda _s: hub._active_subtab == "launch")
    await page.wait_for(lambda _s: bool(modal.query("#launch")))
    pane = modal.query_one("#launch", LaunchPane)
    await _wait_for_launch_pane_ready(page, pane)
    return modal, pane


async def _wait_for_launch_pane_ready(page: AcePage, pane: LaunchPane) -> None:
    def launch_row_is_ready() -> bool:
        try:
            option_list = pane.query_one("#models-panel-list", OptionList)
            option_list.get_option_index("launch:default_model")
            ready = pane._provider_snapshot_worker is None
            ready = ready and any(
                row_id.startswith("bucket:") or not row_id.startswith("launch:")
                for row_id in pane._row_by_id
                if not row_id.startswith("setting:")
            )
        except Exception:
            return False
        return ready

    await wait_for_state(
        page,
        launch_row_is_ready,
        description="Config Launch rows loaded",
    )


async def test_config_center_launch_default_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await _open_config_launch(page)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_launch_default_120x40",
            title="ACE SASE Admin Center — Config Launch child",
        )


async def test_config_center_launch_provider_disabled_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    views = provider_disabled_views()
    disable = provider_disable(
        "codex", expires_at=FROZEN_NOW + 2_520.0, source="visual"
    )
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "claude",
                model_count=11,
                affected_aliases=("small", "large", "xlarge"),
            ),
            provider_status(
                "codex",
                model_count=7,
                active_disable=disable,
                affected_aliases=("medium", "xsmall", "legacy_blog"),
            ),
            provider_status("gemini", model_count=2, cli_available=False),
        ),
        provider_disables={"codex": disable},
        alias_views=tuple(views),
        provider_colors={
            "claude": "#D97757",
            "codex": "#10A37F",
            "gemini": "#87D7FF",
        },
        captured_at=FROZEN_NOW,
    )
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: views)
    monkeypatch.setattr(
        models_panel_provider_state, "build_alias_views", lambda *a, **k: views
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(models_panel_provider_state, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        models_panel_providers,
        "load_provider_routing_snapshot",
        lambda *_a, **_k: snapshot,
    )

    async with AcePage(query='"visual"', patches=patches(), size=(70, 32)) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        _modal, pane = await _open_config_launch(page)
        _highlight_launch_row(pane, "medium")

        def paused_override_row_is_visible() -> bool:
            try:
                option_list = pane.query_one("#models-panel-list", OptionList)
            except Exception:
                return False
            return any(
                "override paused · CODEX disabled" in option.prompt.plain
                for option in option_list.options
            )

        await wait_for_state(
            page,
            paused_override_row_is_visible,
            description="Config Launch paused override row",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_launch_provider_disabled_70x32",
            title="ACE SASE Admin Center — Config Launch provider disabled",
        )
