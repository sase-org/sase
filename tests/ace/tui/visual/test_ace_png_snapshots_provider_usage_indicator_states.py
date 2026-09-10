"""ACE TUI PNG snapshots: usage badge widths, window mixes, states, and palette."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import ProviderDisablesIndicator
from tests._usage_view_helpers import FROZEN_NOW, usage_provider
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
    scope,
    weekly_window,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _entries_projection(*entries: dict[str, Any]) -> SimpleNamespace:
    """Serve prebuilt indicator entries without a provider summary record."""
    return SimpleNamespace(
        entries=tuple(entries), providers=(), generated_at=FROZEN_NOW
    )


async def _snapshot_top_bar(
    ace_png_visual: AcePngSnapshotFixture,
    *,
    size: tuple[int, int],
    name: str,
    title: str,
    theme: str | None = None,
) -> None:
    """Render the artifacts top bar and assert one usage indicator golden."""
    async with AcePage(query='"visual"', patches=patches(), size=size) as page:
        await wait_for_startup(page)
        if theme is not None:
            page.app.theme = theme
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        paint_current_project_chip(page)
        provider_indicator = page.app.query_one(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        provider_indicator._apply_content(now=FROZEN_NOW)
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, name, title=title)


async def test_top_bar_usage_badges_extra_wide_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 160-column bar shows every weekly entry in full with no overflow count."""
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)

    claude = usage_provider(
        "claude",
        used_percent=38.0,
        remaining_percent=62.0,
        attention={"kind": "none", "provider": "claude", "window_key": "weekly"},
        windows=[
            weekly_window(
                key="weekly",
                label="Week",
                used_percent=38.0,
                remaining_percent=62.0,
                resets_at=FROZEN_NOW + 273_840.0,
            )
        ],
        known_constraints=[],
    )
    codex = usage_provider(
        "codex",
        used_percent=55.0,
        remaining_percent=45.0,
        attention={
            "kind": "none",
            "provider": "codex",
            "window_key": "included_weekly",
        },
        windows=[
            weekly_window(
                key="included_weekly",
                label="Codex included weekly allowance",
                used_percent=55.0,
                remaining_percent=45.0,
                resets_at=FROZEN_NOW + 190_800.0,
            )
        ],
        known_constraints=[],
    )
    grok = usage_provider(
        "grok",
        used_percent=3.0,
        remaining_percent=97.0,
        attention={"kind": "none", "provider": "grok", "window_key": "included_weekly"},
        windows=[
            weekly_window(
                key="included_weekly",
                label="Grok included weekly allowance",
                used_percent=3.0,
                remaining_percent=97.0,
                resets_at=FROZEN_NOW + 112_200.0,
            )
        ],
        known_constraints=[],
    )

    patch_projection(monkeypatch, real_projection(claude, codex, grok, now=FROZEN_NOW))

    await _snapshot_top_bar(
        ace_png_visual,
        size=(160, 24),
        name="top_bar_usage_badges_weekly_160x24",
        title="ACE top bar with three weekly usage badges in full at 160 columns",
    )


async def test_top_bar_claude_three_windows_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude's session, weekly-all, and weekly-Fable windows share one bar."""
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)

    session = entry(
        provider="claude",
        window_key="session",
        window_label="Claude five-hour session",
        weekly_all=False,
        period_kind="session",
        duration_seconds=None,
        entry_scope=scope(kind="all_models", product="claude"),
        remaining_percent=18.0,
        seconds_until_reset=7_740.0,
        resets_at=FROZEN_NOW + 7_740.0,
    )
    weekly_all = entry(
        provider="claude",
        window_key="weekly",
        remaining_percent=62.0,
    )
    weekly_fable = entry(
        provider="claude",
        window_key="weekly:claude-fable-5",
        window_label="Claude weekly Fable",
        weekly_all=False,
        period_kind="weekly",
        duration_seconds=None,
        entry_scope=scope(
            kind="product", product="claude", model_ids=("claude-fable-5",)
        ),
        remaining_percent=7.0,
        seconds_until_reset=115_200.0,
        resets_at=FROZEN_NOW + 115_200.0,
        display_attention="very_low",
    )

    patch_projection(
        monkeypatch, _entries_projection(weekly_fable, session, weekly_all)
    )

    await _snapshot_top_bar(
        ace_png_visual,
        size=(140, 24),
        name="top_bar_usage_claude_three_windows_140x24",
        title="ACE top bar with Claude session, weekly, and weekly-Fable badges",
    )


async def test_top_bar_usage_badges_crowded_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 60-column bar keeps routing controls and degrades usage to a count."""
    patch_startup_loaders(monkeypatch)
    default_override = override("codex", "o3", effort="xhigh")
    quiet_top_bar(
        monkeypatch,
        default_override=default_override,
        disables={"claude": disable("claude")},
    )

    patch_projection(
        monkeypatch,
        _entries_projection(
            entry(provider="grok", remaining_percent=4.0, display_attention="very_low"),
            entry(provider="codex", remaining_percent=50.0),
            entry(provider="claude", remaining_percent=62.0),
        ),
    )

    await _snapshot_top_bar(
        ace_png_visual,
        size=(60, 24),
        name="top_bar_usage_badges_crowded_60x24",
        title="ACE top bar with usage disclosure squeezed beside routing at 60 columns",
    )


async def test_top_bar_usage_display_states_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale, reset-passed, unknown-reset, and rejected states render together."""
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)

    stale = entry(
        provider="claude",
        window_key="weekly",
        remaining_percent=62.0,
        freshness="stale",
    )
    reset_passed = entry(
        provider="codex",
        window_key="primary",
        remaining_percent=31.0,
        reset_state="passed",
        seconds_until_reset=0.0,
        resets_at=FROZEN_NOW - 10.0,
    )
    unknown_reset = entry(
        provider="grok",
        window_key="included_weekly",
        remaining_percent=88.0,
        reset_state="unknown",
        seconds_until_reset=None,
        resets_at=None,
    )

    patch_projection(
        monkeypatch, _entries_projection(stale, reset_passed, unknown_reset)
    )

    await _snapshot_top_bar(
        ace_png_visual,
        size=(140, 24),
        name="top_bar_usage_display_states_140x24",
        title="ACE top bar usage badges: stale, reset passed, and unknown reset",
    )


async def test_top_bar_usage_collector_failure_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing collector keeps its warning marker beside healthy badges."""
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)

    healthy = entry(provider="claude", remaining_percent=62.0)
    failing = entry(
        provider="codex",
        window_key="primary",
        remaining_percent=12.0,
        collector_problem=True,
        display_attention="collection_problem",
    )

    patch_projection(monkeypatch, _entries_projection(failing, healthy))

    await _snapshot_top_bar(
        ace_png_visual,
        size=(140, 24),
        name="top_bar_usage_collector_failure_140x24",
        title="ACE top bar usage badges with a failing collector warning marker",
    )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "top_bar_usage_palette_dark_240x24",
            "ACE top bar ten-bucket usage palette - dark theme",
        ),
        (
            "textual-light",
            "top_bar_usage_palette_light_240x24",
            "ACE top bar ten-bucket usage palette - light theme",
        ),
    ],
)
async def test_top_bar_usage_palette_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    """Every ten-bucket remaining-percent decile stays distinct in both themes."""
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)

    deciles = tuple(
        entry(
            provider="claude",
            window_key=f"weekly:bucket-{index}",
            remaining_percent=index * 10.0 + 5.0,
            reset_state="unknown",
            seconds_until_reset=None,
            resets_at=None,
        )
        for index in range(10)
    )

    patch_projection(monkeypatch, _entries_projection(*deciles))

    await _snapshot_top_bar(
        ace_png_visual,
        size=(240, 24),
        name=snapshot_name,
        title=title,
        theme=theme,
    )


async def test_top_bar_usage_no_observation_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An eligible provider with no observed window contributes no badge."""
    patch_startup_loaders(monkeypatch)
    quiet_top_bar(monkeypatch)

    observed = usage_provider(
        "claude",
        used_percent=38.0,
        remaining_percent=62.0,
        attention={"kind": "none", "provider": "claude", "window_key": "weekly"},
        windows=[
            weekly_window(
                key="weekly",
                label="Week",
                used_percent=38.0,
                remaining_percent=62.0,
                resets_at=FROZEN_NOW + 273_840.0,
            )
        ],
        known_constraints=[],
    )
    unobserved = usage_provider(
        "codex",
        used_percent=None,
        remaining_percent=None,
        attention={"kind": "none", "provider": "codex", "window_key": None},
        windows=[],
        known_constraints=[],
        last_full_observation_at=None,
    )

    patch_projection(monkeypatch, real_projection(observed, unobserved, now=FROZEN_NOW))

    await _snapshot_top_bar(
        ace_png_visual,
        size=(140, 24),
        name="top_bar_usage_no_observation_140x24",
        title="ACE top bar with one observed window and one unobserved provider",
    )
