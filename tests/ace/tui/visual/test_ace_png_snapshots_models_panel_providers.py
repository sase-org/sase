"""ACE TUI PNG snapshots for Launch Control provider-routing states."""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.models_panel as models_panel
import sase.ace.tui.modals.models_panel_providers as models_panel_providers
import sase.ace.tui.modals.models_panel_provider_state as models_panel_provider_state
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from textual.widgets import OptionList, Static
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    provider_disable,
    provider_disabled_views,
    provider_soft_disabled_views,
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


def _highlight_row(page: AcePage, row_id: str) -> None:
    panel = page.app.screen
    assert isinstance(panel, ModelsPanel)
    option_list = panel.query_one("#models-panel-list", OptionList)
    panel._set_highlighted_index(option_list, option_list.get_option_index(row_id))
    panel._update_context()


async def test_models_panel_provider_disabled_png_snapshot(
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        panel = ModelsPanel()
        page.app.push_screen(panel)
        await page.expect_modal("ModelsPanel")

        def provider_line_is_visible() -> bool:
            try:
                title = panel.query_one("#models-panel-title", Static)
            except Exception:
                return False
            return "disabled providers: CODEX 42m" in title.content.plain

        def paused_override_row_is_visible() -> bool:
            try:
                option_list = panel.query_one("#models-panel-list", OptionList)
            except Exception:
                return False
            return any(
                "override paused · CODEX disabled" in option.prompt.plain
                for option in option_list.options
            )

        await wait_for_state(
            page,
            provider_line_is_visible,
            description="Launch Control provider disable title line",
        )
        _highlight_row(page, "medium")
        await wait_for_state(
            page,
            paused_override_row_is_visible,
            description="Launch Control paused override row",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_disabled_120x40",
            title="ACE Launch Control - provider disabled worker bucket",
        )


async def test_models_panel_provider_soft_disabled_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    views = provider_soft_disabled_views()
    disable = provider_disable(
        "codex",
        expires_at=FROZEN_NOW + 2_520.0,
        source="visual",
        mode="soft",
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
            provider_status(
                "gemini",
                model_count=2,
                cli_available=False,
                affected_aliases=("xsmall",),
            ),
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
        models_panel,
        "load_provider_routing_snapshot",
        lambda *_a, **_k: snapshot,
    )
    monkeypatch.setattr(
        models_panel_providers,
        "load_provider_routing_snapshot",
        lambda *_a, **_k: snapshot,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        panel = ModelsPanel()
        page.app.push_screen(panel)
        await page.expect_modal("ModelsPanel")

        def provider_line_is_visible() -> bool:
            try:
                title = panel.query_one("#models-panel-title", Static)
            except Exception:
                return False
            return "disabled providers: CODEX soft 42m" in title.content.plain

        def pool_description_is_visible() -> bool:
            try:
                description = panel.query_one("#models-panel-description", Static)
            except Exception:
                return False
            plain = description.content.plain
            return (
                "× gemini/gemini-2.5-pro" in plain
                and "→ ✓ codex/gpt-5.5@high" in plain
                and " soft" not in plain
            )

        await wait_for_state(
            page,
            provider_line_is_visible,
            description="Launch Control soft provider disable title line",
        )
        _highlight_row(page, "xsmall")
        await wait_for_state(
            page,
            pool_description_is_visible,
            description="Launch Control soft-disabled pool description",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_soft_disabled_120x40",
            title="ACE Launch Control - provider soft-disabled",
        )
