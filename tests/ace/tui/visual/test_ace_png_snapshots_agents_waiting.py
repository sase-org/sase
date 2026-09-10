"""ACE TUI PNG visual snapshot coverage for Agents-tab waiting-agent rows."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_contains,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_zoom_fixtures import (
    wait_for_zoom_content,
    waiting_tribe_agents,
    waiting_unknown_agents,
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


def _seed_wait_bead_status_cache() -> None:
    from sase.ace.tui.models.agent_wait_beads import _WAIT_BEAD_STATUS_CACHE

    _WAIT_BEAD_STATUS_CACHE.clear()
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "run-bead"), "in_progress")
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "done-bead"), "closed")
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "open-bead"), "open")


def _seed_single_bead_wait_status_cache() -> None:
    from sase.ace.tui.models.agent_wait_beads import _WAIT_BEAD_STATUS_CACHE

    _WAIT_BEAD_STATUS_CACHE.clear()
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "sase-yz"), "in_progress")
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "sase-alpha.pipeline.review.12"), "open")
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "mixed-bead"), "in_progress")


def _clear_wait_bead_status_cache() -> None:
    from sase.ace.tui.models.agent_wait_beads import _WAIT_BEAD_STATUS_CACHE

    _WAIT_BEAD_STATUS_CACHE.clear()


def _single_bead_wait_agents() -> list[Agent]:
    project_file = "/workspace/sase/visual_project.sase"
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="single-bead-short",
            project_file=project_file,
            status="WAITING",
            start_time=datetime(2026, 5, 9, 10, 30, 0),
            raw_suffix="20260509-103000-single-short",
            agent_name="single.short",
            waiting_for_beads=["sase-yz"],
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="single-bead-long",
            project_file=project_file,
            status="WAITING",
            start_time=datetime(2026, 5, 9, 10, 31, 0),
            raw_suffix="20260509-103100-single-long",
            agent_name="single.long",
            waiting_for_beads=["sase-alpha.pipeline.review.12"],
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="single-bead-mixed",
            project_file=project_file,
            status="WAITING",
            start_time=datetime(2026, 5, 9, 10, 32, 0),
            raw_suffix="20260509-103200-mixed",
            agent_name="mixed.wait",
            waiting_for=["builder"],
            waiting_for_beads=["mixed-bead"],
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="single-bead-builder",
            project_file=project_file,
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 33, 0),
            raw_suffix="20260509-103300-builder",
            agent_name="builder",
            llm_provider="codex",
            model="gpt-5",
        ),
    ]


async def _wait_for_zoom_wait_bead_statuses(page: AcePage) -> None:
    def has_status_badges() -> bool:
        try:
            assert_page_svg_styled_text_contains(
                page,
                "[beads] run-bead ◐, done-bead ●, open-bead ○",
            )
        except AssertionError:
            return False
        return True

    await wait_for_state(
        page,
        has_status_badges,
        description="zoom wait bead status badges",
    )
    await wait_for_visual_idle(page)


async def test_agents_waiting_single_bead_labels_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_single_bead_wait_status_cache()
    try:
        patch_startup_loaders(
            monkeypatch,
            agents=_single_bead_wait_agents(),
        )

        async with AcePage(query='"single-bead"', patches=patches()) as page:
            await wait_for_startup(page)
            await page.press("shift+tab")
            await page.expect_state("tab", "agents")
            await page.expect_state("agent_count", 4)
            await wait_for_svg_contains(page, "sase-yz")
            await wait_for_visual_idle(page)

            assert_page_svg_styled_text_contains(page, "WAITING ◐ sase-yz")
            assert_page_svg_styled_text_contains(
                page,
                "WAITING ○ sase-alpha.pipeline.review.12",
            )
            assert_page_svg_styled_text_contains(page, "WAITING ▶1 ◐1")
            assert_page_svg_contains(page, "Wait:")
            assert_page_svg_contains(page, "[beads]")
            assert_page_svg_contains(page, "sase-yz")
            ace_png_visual.assert_page_png(
                page,
                "agents_waiting_single_bead_labels_120x40",
                title="ACE agents single bead wait labels",
            )
    finally:
        _clear_wait_bead_status_cache()


async def test_agents_waiting_single_bead_labels_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_single_bead_wait_status_cache()
    try:
        patch_startup_loaders(
            monkeypatch,
            agents=_single_bead_wait_agents(),
        )

        async with AcePage(
            query='"single-bead"',
            patches=patches(),
            size=(90, 32),
        ) as page:
            await wait_for_startup(page)
            await page.press("shift+tab")
            await page.expect_state("tab", "agents")
            await page.expect_state("agent_count", 4)
            await page.press("j", "j")
            await wait_for_svg_contains(page, "sase-alpha.pipeline.review.12")
            await wait_for_visual_idle(page)

            assert_page_svg_styled_text_contains(page, "WAITING ◐ sase-yz")
            assert_page_svg_styled_text_contains(
                page,
                "WAITING ○ sase-alpha.pipeline.review.12",
            )
            assert_page_svg_styled_text_contains(page, "WAITING ▶1 ◐1")
            assert_page_svg_contains(page, "sase-alpha.pipeline.review.12")
            ace_png_visual.assert_page_png(
                page,
                "agents_waiting_single_bead_labels_90x32",
                title="ACE agents single bead wait labels narrow",
            )
    finally:
        _clear_wait_bead_status_cache()


async def test_agents_waiting_missing_target_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_wait_bead_status_cache()
    try:
        patch_startup_loaders(
            monkeypatch,
            agents=waiting_unknown_agents(),
        )

        async with AcePage(query='"wait-unknown"', patches=patches()) as page:
            await wait_for_startup(page)
            await page.press("shift+tab")
            await page.expect_state("tab", "agents")
            await page.expect_state("agent_count", 4)
            await wait_for_svg_contains(page, "wait-unknown")
            await wait_for_visual_idle(page)

            assert_page_svg_styled_text_contains(page, "WAITING ✗1 ▶1 ◐1 ✓1 ●1 ?1 ○1")
            assert_page_svg_styled_text_contains(page, "?1 ○1")
            assert_page_svg_styled_text_contains(page, "▶1")
            assert_page_svg_styled_text_contains(page, "◐1")
            assert_page_svg_contains(page, "Wait:")
            assert_page_svg_contains(page, "[agents]")
            assert_page_svg_contains(page, "[beads]")
            assert_page_svg_contains(page, "coder")
            assert_page_svg_contains(page, "builder")
            assert_page_svg_contains(page, "reviewer")
            assert_page_svg_contains(page, "✓")
            assert_page_svg_contains(page, "▶")
            assert_page_svg_contains(page, "✗")
            assert_page_svg_contains(page, "?")
            ace_png_visual.assert_page_png(
                page,
                "agents_waiting_missing_target_row_120x40",
                title="ACE agents missing wait target row and detail",
            )
    finally:
        _clear_wait_bead_status_cache()


async def test_agents_waiting_tribe_target_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=waiting_tribe_agents(),
    )

    async with AcePage(query='"wait-tribe"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        await wait_for_svg_contains(page, "@epic")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "WAITING")
        assert_page_svg_contains(page, "Wait:")
        assert_page_svg_contains(page, "[tribes]")
        assert_page_svg_contains(page, "@epic")
        assert_page_svg_contains(page, "epic.builder")
        assert_page_svg_contains(page, "▶")
        assert "WAITING ?" not in page.export_svg(title="tribe wait assertion")
        ace_png_visual.assert_page_png(
            page,
            "agents_waiting_tribe_target_row_120x40",
            title="ACE agents pending tribe wait row and detail",
        )


async def test_agents_waiting_unknown_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_wait_bead_status_cache()
    try:
        patch_startup_loaders(
            monkeypatch,
            agents=waiting_unknown_agents(),
        )

        async with AcePage(query='"wait-unknown"', patches=patches()) as page:
            await wait_for_startup(page)
            await page.press("shift+tab")
            await page.expect_state("tab", "agents")
            await page.expect_state("agent_count", 4)
            await wait_for_visual_idle(page)
            await page.press("p")
            await page.press("Z")
            await page.expect_modal("ZoomPanelModal")
            await wait_for_zoom_content(
                page,
                "ghost",
                scroll_selector="#zoom-metadata-scroll",
            )
            await _wait_for_zoom_wait_bead_statuses(page)

            assert_page_svg_contains(page, "Wait:")
            assert_page_svg_contains(page, "coder")
            assert_page_svg_contains(page, "builder")
            assert_page_svg_contains(page, "reviewer")
            assert_page_svg_contains(page, "ghost")
            assert_page_svg_contains(page, "✓")
            assert_page_svg_contains(page, "▶")
            assert_page_svg_contains(page, "✗")
            assert_page_svg_contains(page, "?")
            ace_png_visual.assert_page_png(
                page,
                "agents_waiting_unknown_zoom_modal_120x40",
                title="ACE agents waiting unknown zoom modal",
                max_diff_pixels=10_000,
                max_material_diff_pixels=0,
            )
    finally:
        _clear_wait_bead_status_cache()
