"""PNG visual snapshots for the labeled top-bar indicator cluster.

Three goldens pin the Busy cluster with ``tools:`` (live, silent, and bare
monitor), ``bg:``, updates, stash, and inbox all populated: full labels at
220 columns and the compact cluster at 120 and 80 columns. Until-cleared
overrides keep the frame deterministic. The sky ``⚒`` fill is kept (it stays
distinct from the cyan ``⚙`` in the captured frames).
"""

from __future__ import annotations

from datetime import datetime

import pytest

import sase.ace.tui.widgets.alias_overrides_indicator as alias_overrides_indicator
from sase.ace.testing import AcePage
from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
from sase.ace.tui.widgets import (
    AliasOverridesIndicator,
    NotificationIndicator,
    StashedPromptsIndicator,
    UpdatesAvailableIndicator,
)
from sase.llm_provider import TemporaryLLMOverride
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from sase.llm_provider.provider_priority import (
    PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
    TemporaryProviderPriority,
    provider_routing_context_from_parts,
)
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_tool_runs_png_snapshot_shared import (
    TOOL_RUN_EPOCH_INT,
    FakeTime,
    seed_tool_run_surfaces,
    tool_run_glance,
    tool_run_summary,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _override() -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort="xhigh",
    )


def _disable() -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider="codex",
        created_at=100.0,
        expires_at=None,
        source="test",
    )


def _priority() -> TemporaryProviderPriority:
    return TemporaryProviderPriority(
        version=PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
        provider="codex",
        created_at=100.0,
        expires_at=None,
        source="test",
    )


def _busy_context():  # type: ignore[no-untyped-def]
    return provider_routing_context_from_parts(
        {"claude": _disable()}, _priority(), captured_at=100.0
    )


def _tabs() -> list[NotificationTagTab]:
    return [
        NotificationTagTab(tag="hitl", label="Gates", count=5, kind="hitl"),
        NotificationTagTab(tag="beads", label="Beads", count=1, kind="panel"),
        NotificationTagTab(tag=None, label="General", count=18, kind="general"),
    ]


def _seed_busy_tools(
    monkeypatch: pytest.MonkeyPatch,
    page: AcePage,
) -> None:
    """Seed one live run, one silent run, and one bg plus one bare monitor."""
    from sase.ace.tui.actions import _proc_action_observer as observer_module

    seed_tool_run_surfaces(
        monkeypatch,
        glances=[
            tool_run_glance("visual-live", label="check"),
            tool_run_glance(
                "visual-silent",
                label="test",
                last_activity_ts=TOOL_RUN_EPOCH_INT - 240,
            ),
        ],
        summaries={
            "visual-live": tool_run_summary("visual-live"),
            "visual-silent": tool_run_summary("visual-silent"),
        },
    )
    # Pin the observer's wall clock to the fixture epoch so the seeded
    # live run reads live and the 4-minute-idle run reads silent.
    monkeypatch.setattr(observer_module, "time", FakeTime)
    started_at = datetime(2026, 7, 28, 12, 0)
    page.app._replace_proc_projection(
        ProcProjection(
            rows=(
                ObservedProc(
                    proc_id="visual-bg",
                    proc_type="sync",
                    cl_name="",
                    project_file="",
                    status="running",
                    message="running",
                    started_at=started_at,
                    display_name="sync",
                    origin="ace",
                ),
                ObservedProc(
                    proc_id="visual-mon",
                    proc_type="detached",
                    cl_name="sase",
                    project_file="",
                    status="running",
                    message="running",
                    started_at=started_at,
                    origin="monitor",
                    proc_name="visual--mon",
                ),
            ),
        )
    )
    page.app._update_proc_indicator()


async def _drive_busy(page: AcePage, monkeypatch: pytest.MonkeyPatch) -> None:
    await wait_for_startup(page)
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    await page.expect_state("tab", "patches")
    await wait_for_svg_contains(page, "visual_auth")
    _seed_busy_tools(monkeypatch, page)
    page.app.query_one("#updates-indicator", UpdatesAvailableIndicator).set_available(
        3, core=True, agent_cli_count=2
    )
    page.app.query_one("#alias-overrides-indicator", AliasOverridesIndicator).refresh()
    page.app.query_one("#stashed-prompts-indicator", StashedPromptsIndicator).set_count(
        4
    )
    page.app.query_one("#notification-indicator", NotificationIndicator).set_tabs(
        _tabs()
    )

    def _cluster_text() -> str:
        cluster = page.app.query_one("#top-bar-indicators")
        return "".join(
            child.render().plain for child in cluster.children if child.display
        )

    await wait_for_state(
        page,
        lambda: "tools:" in _cluster_text() and "bg:" in _cluster_text(),
        description="busy top-bar cluster",
    )
    page.app.refresh(layout=True)
    await page.app.wait_for_refresh()
    await wait_for_visual_idle(page)


async def test_top_bar_indicators_full_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All six groups visible at a wide size with full labels."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda: {"medium": _override()},
    )
    monkeypatch.setattr(
        alias_overrides_indicator,
        "peek_provider_routing_context",
        lambda *a, **k: _busy_context(),
    )

    async with AcePage(query='"visual"', patches=patches(), size=(220, 40)) as page:
        await _drive_busy(page, monkeypatch)
        ace_png_visual.assert_page_png(
            page,
            "top_bar_indicators_full_220x40",
            title="ACE labeled top-bar indicators full",
        )


async def test_top_bar_indicators_compact_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same busy six-group state at a narrow size with labels dropped together."""
    from sase.llm_provider.provider_priority import (
        provider_routing_context_from_parts as _ctx_from_parts,
    )

    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda: {"medium": _override()},
    )
    empty = _ctx_from_parts({}, None, captured_at=100.0)
    monkeypatch.setattr(
        alias_overrides_indicator,
        "peek_provider_routing_context",
        lambda *a, **k: empty,
    )

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        monkeypatch.setattr(
            alias_overrides_indicator,
            "peek_provider_routing_context",
            lambda *a, **k: _busy_context(),
        )
        _seed_busy_tools(monkeypatch, page)
        page.app.query_one(
            "#updates-indicator", UpdatesAvailableIndicator
        ).set_available(3, core=True, agent_cli_count=2)
        page.app.query_one(
            "#alias-overrides-indicator", AliasOverridesIndicator
        ).refresh()
        page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        ).set_count(4)
        page.app.query_one("#notification-indicator", NotificationIndicator).set_tabs(
            _tabs()
        )

        def _compact_cluster_text() -> str:
            cluster = page.app.query_one("#top-bar-indicators")
            return "".join(
                child.render().plain for child in cluster.children if child.display
            )

        await wait_for_state(
            page,
            lambda: "⚒" in _compact_cluster_text() and "⚙" in _compact_cluster_text(),
            description="busy compact top-bar cluster",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "top_bar_indicators_compact_120x40",
            title="ACE labeled top-bar indicators compact",
        )


async def test_top_bar_indicators_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Busy cluster at 80 columns stays in bounds with icons intact."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        alias_overrides_indicator,
        "get_active_alias_overrides",
        lambda: {"medium": _override()},
    )
    monkeypatch.setattr(
        alias_overrides_indicator,
        "peek_provider_routing_context",
        lambda *a, **k: _busy_context(),
    )

    async with AcePage(query='"visual"', patches=patches(), size=(80, 40)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await wait_for_svg_contains(page, "visual_auth")
        _seed_busy_tools(monkeypatch, page)
        page.app.query_one(
            "#updates-indicator", UpdatesAvailableIndicator
        ).set_available(3, core=True, agent_cli_count=2)
        page.app.query_one(
            "#alias-overrides-indicator", AliasOverridesIndicator
        ).refresh()
        page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        ).set_count(4)
        page.app.query_one("#notification-indicator", NotificationIndicator).set_tabs(
            _tabs()
        )

        def _narrow_cluster_text() -> str:
            cluster = page.app.query_one("#top-bar-indicators")
            return "".join(
                child.render().plain for child in cluster.children if child.display
            )

        # At 80 columns the cluster is compact: labels drop, chips stay.
        await wait_for_state(
            page,
            lambda: "⚒" in _narrow_cluster_text() and "⚙" in _narrow_cluster_text(),
            description="busy narrow top-bar cluster",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "top_bar_indicators_compact_80x40",
            title="ACE labeled top-bar indicators narrow",
        )
