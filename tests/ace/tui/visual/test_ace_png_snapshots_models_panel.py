"""ACE TUI PNG snapshots for primary Launch Control states."""

from __future__ import annotations

from collections.abc import Callable

import pytest

import sase.ace.tui.modals.models_panel as models_panel
import sase.ace.tui.modals.models_panel_providers as models_panel_providers
import sase.ace.tui.modals.models_panel_provider_state as models_panel_provider_state
from sase.ace.testing import AcePage
from sase.ace.tui.modals import LaunchPane, ModelsPanel
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.llm_provider import AliasView
from textual.widgets import OptionList, Static
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    builtin_only_views,
    calm_views,
    custom_builtin_warning_views,
    effort_snapshot,
    long_pool_views,
    override_views,
    pool_effort_views,
    provider_disable,
    provider_disabled_views,
    provider_soft_disabled_views,
    provider_status,
    runner_limit_snapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
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


async def _wait_for_models_panel_ready(page: AcePage) -> None:
    def launch_row_is_ready() -> bool:
        screen = page.app.screen
        if not isinstance(screen, ModelsPanel):
            return False
        try:
            option_list = screen.query_one("#models-panel-list", OptionList)
            option_list.get_option_index("launch:default_model")
            ready = screen._provider_snapshot_worker is None
            ready = ready and any(
                row_id.startswith("bucket:") or not row_id.startswith("launch:")
                for row_id in screen._row_by_id
                if not row_id.startswith("setting:")
            )
        except Exception:
            return False
        return ready

    await wait_for_state(
        page,
        launch_row_is_ready,
        description="Launch Control rows loaded",
    )


def _highlight_row(page: AcePage, row_id: str) -> None:
    screen = page.app.screen
    assert isinstance(screen, ModelsPanel)
    _highlight_launch_row(screen, row_id)


def _highlight_launch_row(pane: LaunchPane | ModelsPanel, row_id: str) -> None:
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


async def test_models_panel_empty_custom_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, builtin_only_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_empty_custom_120x40",
            title="ACE Launch Control (empty custom section)",
        )


async def test_models_panel_default_png_snapshot(
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

        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_default_120x40",
            title="ACE Launch Control (no overrides)",
        )


async def test_models_panel_default_effort_override_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_effort_snapshot",
        lambda self: (effort_snapshot(), True),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        await wait_for_svg_contains(page, "override · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_override_120x40",
            title="ACE Launch Control - active default-effort override",
        )


async def test_models_panel_runner_limit_override_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_runner_limit_snapshot",
        lambda self: (runner_limit_snapshot(), True),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        await wait_for_svg_contains(page, "override · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_runner_limit_override_120x40",
            title="ACE Launch Control - active runner-limit override",
        )


async def test_models_panel_smartest_max_effort_png_snapshot(
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
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "xlarge")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_smartest_max_effort_120x40",
            title="ACE Launch Control (maximum-effort xlarge target)",
        )


async def test_models_panel_pool_effort_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Show the default, pool availability/next member, and row effort."""
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, pool_effort_views)
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "xsmall")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_pool_effort_120x40",
            title="ACE Launch Control (pool and effort)",
        )


async def test_models_panel_long_pool_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrapped 4-member pool must show every member without clipping the
    footer or the modal border."""
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, long_pool_views)
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "xsmall")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_long_pool_120x40",
            title="ACE Launch Control (long pool wraps 3+ rows)",
        )


async def test_models_panel_effort_provenance_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, pool_effort_views)
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "focused")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_provenance_120x40",
            title="ACE Launch Control (effort provenance)",
        )


async def test_models_panel_pool_suspended_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, lambda: pool_effort_views(suspended=True))
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "xsmall")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_pool_suspended_120x40",
            title="ACE Launch Control (pool suspended by override)",
        )


async def test_models_panel_overrides_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, override_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")

        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_overrides_120x40",
            title="ACE Launch Control (overrides active)",
        )


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


async def test_models_panel_custom_builtin_warning_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, custom_builtin_warning_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "small")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_custom_builtin_warning_120x40",
            title="ACE Launch Control (misplaced builtin warning)",
        )
