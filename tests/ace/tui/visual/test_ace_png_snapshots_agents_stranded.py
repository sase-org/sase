"""PNG coverage for stranded bead rows and clan summaries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._agent_tree_fold import agent_fold_key
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_NOW = datetime(2026, 10, 1, 12, 0)


def _agents() -> list[Agent]:
    common = {
        "project_file": "/tmp/visual/visual.sase",
        "agent_clan": "sase-visual",
        "agent_clan_generation": "visual-generation",
        "tribe": "epic",
        "llm_provider": "codex",
        "model": "gpt-6",
    }
    leaf = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-leaf",
        status="DONE",
        start_time=_NOW,
        stop_time=_NOW,
        raw_suffix="leaf",
        agent_name="sase-visual.1",
        phase_bead_id="sase-visual.1",
        **common,
    )
    waiter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-waiter",
        status="WAITING",
        start_time=_NOW,
        raw_suffix="waiter",
        agent_name="sase-visual.2",
        phase_bead_id="sase-visual.2",
        waiting_for=["sase-visual.1"],
        waiting_for_beads=["sase-visual.1"],
        **common,
    )
    land = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-land",
        status="WAITING",
        start_time=_NOW,
        raw_suffix="land",
        agent_name="sase-visual.land",
        epic_bead_id="sase-visual",
        waiting_for=["sase-visual.2"],
        **common,
    )
    return [leaf, waiter, land]


def _nested_chain_agents() -> list[Agent]:
    common = {
        "project_file": "/tmp/visual/visual.sase",
        "agent_clan_generation": "nested-generation",
        "tribe": "epic",
        "llm_provider": "codex",
        "model": "gpt-6",
    }
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent",
        status="DONE",
        start_time=_NOW,
        stop_time=_NOW,
        raw_suffix="parent",
        agent_name="sase-1n6.5",
        phase_bead_id="sase-1n6.5",
        agent_clan="sase-1n6",
        **common,
    )
    sibling = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-sibling",
        status="DONE",
        start_time=_NOW,
        stop_time=_NOW,
        raw_suffix="sibling",
        agent_name="sase-1n6.5.1.1",
        phase_bead_id="sase-1n6.5.1.1",
        agent_clan="sase-1n6.5.1",
        **common,
    )
    leaf = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-leaf",
        status="DONE",
        start_time=_NOW,
        stop_time=_NOW,
        raw_suffix="leaf",
        agent_name="sase-1n6.5.1.2",
        phase_bead_id="sase-1n6.5.1.2",
        agent_clan="sase-1n6.5.1",
        **common,
    )
    land = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-land",
        status="WAITING",
        start_time=_NOW,
        raw_suffix="land",
        agent_name="sase-1n6.5.1.land",
        epic_bead_id="sase-1n6.5.1",
        agent_clan="sase-1n6.5.1",
        waiting_for_beads=["sase-1n6.5.1.2"],
        **common,
    )
    return [parent, sibling, leaf, land]


def _nested_chain_report() -> StrandedReport:
    leaf_id = "sase-1n6.5.1.2"
    verdicts = (
        StrandedWorkVerdict(
            bead_id="sase-1n6",
            kind="epic",
            state="blocked",
            blocked_by=(leaf_id,),
        ),
        StrandedWorkVerdict(
            bead_id="sase-1n6.5",
            kind="phase",
            state="blocked",
            parent_id="sase-1n6",
            blocked_by=(leaf_id,),
        ),
        StrandedWorkVerdict(
            bead_id="sase-1n6.5.1",
            kind="epic",
            state="blocked",
            parent_id="sase-1n6.5",
            blocked_by=(leaf_id,),
        ),
        StrandedWorkVerdict(
            bead_id=leaf_id,
            kind="phase",
            state="stranded",
            reason="kept",
            since=_NOW.timestamp(),
            parent_id="sase-1n6.5.1",
        ),
    )
    return StrandedReport(
        report=StrandedWorkReport(
            verdicts=verdicts,
            stranded_ids=(leaf_id,),
            blocked_ids=("sase-1n6", "sase-1n6.5", "sase-1n6.5.1"),
        ),
        titles={},
        generated_at=_NOW.timestamp(),
    )


def _report() -> StrandedReport:
    verdicts = (
        StrandedWorkVerdict(
            bead_id="sase-visual",
            kind="epic",
            state="blocked",
            blocked_by=("sase-visual.1",),
        ),
        StrandedWorkVerdict(
            bead_id="sase-visual.1",
            kind="phase",
            state="stranded",
            reason="kept",
            since=_NOW.timestamp(),
            parent_id="sase-visual",
        ),
        StrandedWorkVerdict(
            bead_id="sase-visual.2",
            kind="phase",
            state="blocked",
            blocked_by=("sase-visual.1",),
        ),
    )
    return StrandedReport(
        report=StrandedWorkReport(
            verdicts=verdicts,
            stranded_ids=("sase-visual.1",),
            blocked_ids=("sase-visual", "sase-visual.2"),
        ),
        titles={},
        generated_at=_NOW.timestamp(),
    )


async def test_agents_stranded_rows_and_clan_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _NOW)
    patch_startup_loaders(monkeypatch, agents=_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        from sase.ace.tui.models import agent_stranded

        monkeypatch.setattr(
            page.app,
            "_schedule_bead_confirmation_warmup",
            lambda **_: None,
        )
        agent_stranded._STRANDED_REPORT_CACHE.set("visual", _report(), "visual-store")
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)
        await page.press("l")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "STRANDED")
        assert_page_svg_contains(page, "⚐1")
        info_panel = page.app.query_one("#agent-info-panel")
        assert "⚐ 1 stranded" in info_panel._build_display_text().plain
        assert_page_svg_contains(page, "stranded")
        assert_page_svg_contains(page, "▲")
        ace_png_visual.assert_page_png(
            page,
            "agents_stranded_rows_and_clan_120x40",
            title="ACE stranded work in the Agents tab",
        )


async def test_agents_stranded_nested_chain_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, _NOW)
    patch_startup_loaders(monkeypatch, agents=_nested_chain_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        from sase.ace.tui.models import agent_stranded

        monkeypatch.setattr(
            page.app,
            "_schedule_bead_confirmation_warmup",
            lambda **_: None,
        )
        agent_stranded._STRANDED_REPORT_CACHE.set(
            "visual", _nested_chain_report(), "visual-store"
        )
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)

        leaf_clan = next(
            agent
            for agent in page.app._agents
            if agent.is_clan_container and agent.agent_clan == "sase-1n6.5.1"
        )
        ancestor_clan = next(
            agent
            for agent in page.app._agents
            if agent.is_clan_container and agent.agent_clan == "sase-1n6"
        )
        leaf_fold_key = agent_fold_key(leaf_clan)
        ancestor_fold_key = agent_fold_key(ancestor_clan)
        assert leaf_fold_key is not None
        assert ancestor_fold_key is not None
        page.app._fold_manager.expand(leaf_fold_key)
        page.app._fold_manager.collapse(ancestor_fold_key)
        page.app._refilter_agents(refresh_content_index=False)
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "sase-1n6")
        assert_page_svg_contains(page, "sase-1n6.5.1")
        assert_page_svg_contains(page, "⚐1")
        assert_page_svg_contains(page, "▲")
        assert_page_svg_contains(page, "STRANDED")
        assert_page_svg_contains(page, "⚐")
        ace_png_visual.assert_page_png(
            page,
            "agents_stranded_nested_chain_120x40",
            title="ACE nested stranded epic clan chain",
        )


@pytest.mark.parametrize(
    ("agent_name", "snapshot_name", "expected"),
    (
        (
            "sase-visual.1",
            "agents_stranded_detail_header_120x40",
            "STRANDED",
        ),
        (
            "sase-visual.2",
            "agents_stranded_blocked_detail_120x40",
            "blocked",
        ),
    ),
)
async def test_agents_stranded_detail_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    agent_name: str,
    snapshot_name: str,
    expected: str,
) -> None:
    pin_agents_visual_now(monkeypatch, _NOW)
    patch_startup_loaders(monkeypatch, agents=_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        from sase.ace.tui.models import agent_stranded

        monkeypatch.setattr(
            page.app, "_schedule_bead_confirmation_warmup", lambda **_: None
        )
        agent_stranded._STRANDED_REPORT_CACHE.set("visual", _report(), "visual-store")
        selected_agent = next(
            agent for agent in _agents() if agent.agent_name == agent_name
        )
        page.app._agents = [
            replace(
                selected_agent,
                agent_clan=None,
                agent_clan_generation=None,
                tribe=None,
            )
        ]
        page.app._current_group_key = None
        page.app._agent_panels_grouped = True
        page.app.current_idx = 0
        page.app._refresh_agents_display(list_changed=True)
        page.app.current_idx = -1
        page.app.current_idx = 0
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, expected)
        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=f"ACE {expected} stranded detail callout",
        )


async def test_agents_stranded_resolve_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ended = datetime(2026, 10, 22, 6, 28, tzinfo=UTC)
    generated = ended.timestamp() + 31 * 3600
    pin_agents_visual_now(monkeypatch, _NOW)
    patch_startup_loaders(monkeypatch, agents=_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)

        from sase.ace.tui.modals.stranded_resolve_modal import StrandedResolveModal
        from sase.ace.tui.models import agent_stranded
        from sase.ace.tui.models.stranded_resolve import build_stranded_resolve_view

        monkeypatch.setattr(
            page.app, "_schedule_bead_confirmation_warmup", lambda **_: None
        )
        leaf_id = "sase-visual.1"
        report = StrandedReport(
            report=StrandedWorkReport(
                verdicts=(
                    StrandedWorkVerdict(
                        bead_id=leaf_id,
                        kind="phase",
                        state="stranded",
                        reason="kept",
                        last_turn=f"{leaf_id}--3",
                        since=ended.timestamp(),
                        parent_id="sase-visual",
                        blocks=(
                            "sase-visual.2",
                            "sase-visual.3",
                            "sase-visual.4",
                            "sase-visual.5",
                            "sase-visual.6",
                            "sase-visual",
                        ),
                    ),
                ),
                stranded_ids=(leaf_id,),
            ),
            titles={leaf_id: "Live proof"},
            generated_at=generated,
        )
        agent_stranded._STRANDED_REPORT_CACHE.set("visual", report, "visual-store")
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)
        monkeypatch.setattr(
            page.app, "_refresh_agents_display_debounced", lambda **_: None
        )
        view = build_stranded_resolve_view("visual", leaf_id)
        assert view is not None
        page.app.push_screen(StrandedResolveModal(view))
        await page.expect_modal("StrandedResolveModal")
        await wait_for_svg_contains(page, "Stranded phase")
        await wait_for_svg_contains(page, "Close bead")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Stranded phase")
        assert_page_svg_contains(page, "Live proof")
        assert_page_svg_contains(page, "Continue")
        ace_png_visual.assert_page_png(
            page,
            "agents_stranded_resolve_modal_120x40",
            title="ACE stranded resolve modal",
        )
