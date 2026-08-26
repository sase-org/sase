"""ACE TUI PNG visual snapshot coverage for Agents-tab context zoom modals."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import AcePage
from sase.ace.tui.modals.zoom_panel_rendering import renderable_to_text
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_zoom_fixtures import (
    context_artifact_reads,
    context_memory_reads,
    context_opened_workspaces,
    context_skill_uses,
    wait_for_metadata_zoom_resolved,
    wait_for_zoom_content,
    zoom_agent,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agents_context_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[zoom_agent(tmp_path, include_plan=True)],
        artifact_reads=context_artifact_reads(),
        memory_reads=context_memory_reads(),
        skill_uses=context_skill_uses(),
        opened_workspaces=context_opened_workspaces(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("p")
        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await wait_for_zoom_content(
            page,
            "SASE CONTEXT",
            scroll_selector="#zoom-metadata-scroll",
        )

        metadata_panel = page.app.screen.query_one(
            "#zoom-metadata-panel",
            AgentPromptPanel,
        )
        metadata = renderable_to_text(metadata_panel.content) or ""
        assert metadata.index("▸ PLAN") < metadata.index("▸ ARTIFACTS")
        assert metadata.index("▸ ARTIFACTS") < metadata.index("▸ MEMORY")
        assert metadata.index("▸ MEMORY") < metadata.index("▸ SKILLS")
        assert metadata.index("▸ SKILLS") < metadata.index("▸ WORKSPACES")
        for expected in (
            "src/app.py",
            "generated_skills.md",
            "sase_plan",
            "sase-core",
            "plan:202608/design.md",
            "research:202608/prior-art.md",
        ):
            assert expected in metadata
        assert metadata.index("Reads:") < metadata.index("Deltas:")
        assert "coder" in metadata
        assert "plan" in metadata

        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "PLAN")
        assert_page_svg_contains(page, "tale")
        assert_page_svg_contains(page, "Unified agent context")
        assert_page_svg_contains(page, "ARTIFACTS")
        assert_page_svg_contains(page, "Reads:")
        assert_page_svg_contains(page, "Deltas:")
        ace_png_visual.assert_page_png(
            page,
            "agents_context_zoom_modal_120x40",
            title="ACE agents context zoom modal",
        )

        scroll = page.app.screen.query_one("#zoom-metadata-scroll", VerticalScroll)
        assert scroll.max_scroll_y > 0
        await page.press("G")
        await page.wait_for(lambda _s: scroll.scroll_y == scroll.max_scroll_y)
        assert_page_svg_contains(page, "▣")
        assert_page_svg_contains(page, "sase-core")


async def test_agents_metadata_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[zoom_agent(tmp_path, include_xprompts=True)],
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("p")
        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await wait_for_zoom_content(
            page,
            "Xprompts:",
            scroll_selector="#zoom-metadata-scroll",
        )
        await wait_for_metadata_zoom_resolved(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_metadata_zoom_modal_120x40",
            title="ACE agents metadata zoom modal",
        )
