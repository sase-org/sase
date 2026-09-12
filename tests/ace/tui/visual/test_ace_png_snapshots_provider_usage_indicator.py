"""ACE TUI PNG snapshot: top-bar indicators plus usage attention."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sase.ace.testing import AcePage
from sase.ace.tui.widgets import (
    AliasOverridesIndicator,
    LLMOverrideIndicator,
    ProviderUsageIndicator,
    UpdatesAvailableIndicator,
)
from sase.llm_provider.config import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from tests._usage_view_helpers import FROZEN_NOW, usage_provider, usage_window
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._provider_usage_indicator_fixtures import (
    disable,
    entry,
    override,
    paint_current_project_chip,
    patch_projection,
    quiet_top_bar,
    real_projection,
    weekly_window,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_top_bar_usage_attention_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    default_override = override("codex", "o3", effort="xhigh")
    alias_override = override("claude", "opus", effort="max")
    quiet_top_bar(
        monkeypatch,
        default_override=default_override,
        alias_overrides={
            launch_model_setting_override_key(DEFAULT_MODEL_FIELD): default_override,
            "medium": alias_override,
        },
        disables={"claude": disable("claude")},
        now=100.0,
    )
    patch_projection(
        monkeypatch,
        SimpleNamespace(
            entries=(
                entry(
                    provider="grok",
                    remaining_percent=4.0,
                    vendor_state="rejected",
                    display_attention="rejected",
                ),
                entry(
                    provider="codex",
                    remaining_percent=12.0,
                    display_attention="low",
                ),
            ),
            providers=(),
            generated_at=100.0,
        ),
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(80, 24),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        updates = page.app.query_one("#updates-indicator", UpdatesAvailableIndicator)
        updates.set_available(3, core=True, agent_cli_count=2)
        page.app.query_one("#llm-override-indicator", LLMOverrideIndicator)
        page.app.query_one("#alias-overrides-indicator", AliasOverridesIndicator)
        paint_current_project_chip(page)
        usage_indicator = page.app.query_one(
            "#provider-usage-indicator",
            ProviderUsageIndicator,
        )
        usage_indicator._apply_content(now=100.0)
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "top_bar_usage_attention_80x24",
            title="ACE header usage cluster beside a crowded control row at 80 columns",
        )


async def test_top_bar_compact_usage_badges_wide_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three providers show distinct ten-bucket colors, icons, and countdowns."""
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)

    claude = usage_provider(
        "claude",
        used_percent=22.0,
        remaining_percent=78.0,
        attention={"kind": "none", "provider": "claude", "window_key": "weekly"},
        windows=[
            weekly_window(
                key="weekly",
                label="Week",
                used_percent=22.0,
                remaining_percent=78.0,
                resets_at=FROZEN_NOW + 273_840.0,
            )
        ],
        known_constraints=[],
    )
    codex = usage_provider(
        "codex",
        used_percent=85.0,
        remaining_percent=15.0,
        attention={"kind": "low", "provider": "codex", "window_key": "primary"},
        windows=[
            usage_window(
                key="primary",
                label="Codex",
                used_percent=85.0,
                remaining_percent=15.0,
                resets_at=FROZEN_NOW + 7_740.0,
                applicability={"kind": "account"},
            )
        ],
        known_constraints=[],
    )
    grok = usage_provider(
        "grok",
        used_percent=8.0,
        remaining_percent=92.0,
        attention={"kind": "none", "provider": "grok", "window_key": "included_weekly"},
        windows=[
            weekly_window(
                key="included_weekly",
                label="Grok included weekly allowance",
                used_percent=8.0,
                remaining_percent=92.0,
                resets_at=FROZEN_NOW + 112_200.0,
            )
        ],
        known_constraints=[],
    )

    patch_projection(monkeypatch, real_projection(claude, codex, grok, now=FROZEN_NOW))

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(120, 24),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        paint_current_project_chip(page)
        usage_indicator = page.app.query_one(
            "#provider-usage-indicator",
            ProviderUsageIndicator,
        )
        usage_indicator._apply_content(now=FROZEN_NOW)
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "top_bar_compact_usage_badges_120x24",
            title=(
                "ACE top bar with three provider-colored compact usage badges "
                "at 120 columns"
            ),
        )
