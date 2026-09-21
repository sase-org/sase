"""sase's TUI PNG visual snapshots for the status-row launch-context cluster.

Epic sase-14y, phase 2: the launch-default model/effort and current-project
chips leave the top bar and render as one labeled cluster at the far right of
every tab's status row. These frames pin the Agents, Artifacts, and Services
rows at 120x40, plus an override-state and a compact 60x24 case.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from textual.widgets import Static

import sase.ace.tui.widgets.launch_context_source as launch_context_source
from sase.ace.testing import AcePage
from sase.ace.tui.widgets import LaunchContextBar, LLMOverrideIndicator
from sase.llm_provider.model_launch_settings import (
    LaunchModelSettingSnapshot,
    launch_model_setting_override_key,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_axe_png_snapshot_fixtures import axe_bgcmd_data
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._provider_usage_indicator_fixtures import quiet_top_bar
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _pin_launch_default(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str = "claude",
    model: str = "opus-5",
    effort: str = "high",
) -> None:
    """Pin the resolved launch default (and its pill label) to one provider."""

    def _snapshot(
        field: object, *_args: object, **_kwargs: object
    ) -> LaunchModelSettingSnapshot:
        return LaunchModelSettingSnapshot(
            field=field,  # type: ignore[arg-type]
            config_path=f"llm_provider.{field}",
            raw_value=f"{provider}/{model}",
            provider=provider,
            model=model,
            effort=effort,
            provenance="shipped",
            referenced_alias=None,
            override_key=launch_model_setting_override_key(field),  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        launch_context_source, "build_launch_model_setting_snapshot", _snapshot
    )
    # Pinned so the goldens do not depend on which provider plugins the
    # capturing host has installed.
    monkeypatch.setattr(
        launch_context_source,
        "format_model_directive_label",
        lambda *_args, **_kwargs: model,
    )


def _until_cleared_override() -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider="claude",
        model="opus-5",
        raw_model="claude/opus-5",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort="high",
    )


async def _wait_for_cluster(
    page: AcePage,
    bar_id: str,
    *,
    pill: str,
) -> LaunchContextBar:
    """Wait until the named row's cluster paints the resolved model pill."""

    bar = page.app.query_one(f"#{bar_id}", LaunchContextBar)
    model_view = bar.query_one(LLMOverrideIndicator)
    await wait_for_state(
        page,
        lambda: model_view.render().plain == pill,
        description=f"resolved cluster pill {pill} on {bar_id}",
    )
    return bar


async def test_launch_context_bar_agents_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 12, 12, 3, 0))
    quiet_top_bar(monkeypatch)
    _pin_launch_default(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(120, 40),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await _wait_for_cluster(page, "launch-context-bar-agents", pill="opus-5@high")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "launch_context_bar_agents_120x40",
            title="ACE launch-context cluster on the Agents status row",
        )


async def test_launch_context_bar_artifacts_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)
    _pin_launch_default(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(120, 40),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _wait_for_cluster(
            page, "launch-context-bar-artifacts", pill="opus-5@high"
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "launch_context_bar_artifacts_120x40",
            title="ACE launch-context cluster on the Artifacts status row",
        )


async def test_launch_context_bar_services_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, axe_data=axe_bgcmd_data())
    quiet_top_bar(monkeypatch)
    _pin_launch_default(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(120, 40),
    ) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await _wait_for_cluster(page, "launch-context-bar-axe", pill="opus-5@high")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "launch_context_bar_services_120x40",
            title="ACE launch-context cluster on the Services status row",
        )


async def test_launch_context_bar_override_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 12, 12, 3, 0))
    quiet_top_bar(monkeypatch, default_override=_until_cleared_override())
    _pin_launch_default(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(120, 40),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        bar = await _wait_for_cluster(
            page, "launch-context-bar-agents", pill="CLAUDE(opus-5)@high ∞"
        )
        await wait_for_state(
            page,
            lambda: (
                bar.query_one("#launch-model-label", Static).render().plain
                == "override "
            ),
            description="override lane label",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "launch_context_bar_override_120x40",
            title="ACE launch-context cluster with an active default override",
        )


async def test_launch_context_bar_compact_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)
    _pin_launch_default(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(60, 24),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        bar = await _wait_for_cluster(
            page, "launch-context-bar-artifacts", pill="opus-5@high"
        )
        await wait_for_state(
            page,
            lambda: bar.density == "compact",
            description="compact cluster density",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "launch_context_bar_compact_60x24",
            title="ACE launch-context cluster compact at 60 columns",
        )


async def test_launch_context_bar_full_density_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, axe_data=axe_bgcmd_data())
    quiet_top_bar(monkeypatch)
    _pin_launch_default(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(160, 40),
    ) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        bar = await _wait_for_cluster(
            page, "launch-context-bar-axe", pill="opus-5@high"
        )
        await wait_for_state(
            page,
            lambda: bar.density == "full",
            description="full cluster density",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "launch_context_bar_full_density_160x40",
            title="ACE launch-context cluster full density at 160 columns",
        )
