"""ACE TUI PNG visual snapshot coverage for the Agents tab.

ChangeSpecs-tab and footer snapshots live in ``test_ace_png_snapshots``.
Shared fixtures live in ``_ace_png_snapshot_helpers``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    agents_with_stopped_status,
    changespecs,
    patch_startup_loaders,
    sibling_agents,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


def _assert_page_svg_contains(page: AcePage, text: str) -> None:
    svg = page.export_svg(title="ACE visual assertion")
    svg_plain = svg.replace("&#160;", " ")
    assert text in svg_plain


async def test_agent_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_list_120x40",
            title="ACE agents list",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agent_stopped_status_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents_with_stopped_status())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        _assert_page_svg_contains(page, "Ø STOPPED")
        ace_png_visual.assert_page_png(
            page,
            "agents_stopped_status_120x40",
            title="ACE agents stopped status",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        initial_idx = page.app.current_idx
        for _ in range(8):
            await page.press("j")
            if page.app.current_idx != initial_idx:
                break
        else:
            raise AssertionError("j navigation did not move off the initial agent row")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_selected_row_120x40",
            title="ACE agents selected row",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


def _zoom_agent(tmp_path: Path, *, include_xprompts: bool = False) -> Agent:
    diff_path = tmp_path / "visual_zoom.diff"
    diff_path.write_text(
        "\n".join(
            [
                "diff --git a/src/app.py b/src/app.py",
                "index 1111111..2222222 100644",
                "--- a/src/app.py",
                "+++ b/src/app.py",
                "@@ -1,5 +1,8 @@",
                " def render_dashboard():",
                "-    return old_summary()",
                "+    summary = build_zoom_summary()",
                "+    summary.enable_live_refresh = True",
                "+    return summary",
                "",
                " def footer_hints():",
                "+    return 'j/k scroll  q close'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts_dir: Path | None = None
    if include_xprompts:
        artifacts_dir = tmp_path / "visual_zoom_artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "xprompts.json").write_text(
            json.dumps(
                [
                    {
                        "name": "gh",
                        "kind": "workflow",
                        "positional": ["sase-org/sase"],
                        "named": {},
                        "tags": ["vcs"],
                    },
                    {
                        "name": "propose",
                        "kind": "workflow",
                        "positional": [],
                        "named": {"note": "metadata"},
                        "tags": ["propose"],
                    },
                    {
                        "name": "review_checklist",
                        "kind": "part",
                        "positional": [],
                        "named": {},
                        "tags": [],
                    },
                ]
            ),
            encoding="utf-8",
        )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-zoom",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 9, 10, 20, 0),
        stop_time=datetime(2026, 5, 9, 10, 28, 45),
        raw_suffix="20260509-102000-zoom",
        agent_name="zoom.snapshot.agent",
        llm_provider="codex",
        model="gpt-5",
        diff_path=str(diff_path),
        artifacts_dir=str(artifacts_dir) if artifacts_dir is not None else None,
    )


def _context_memory_reads() -> list[MemoryReadEvent]:
    return [
        MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="visual-read-generated-skills",
            timestamp="2026-06-14T14:22:08+00:00",
            project="visual",
            cwd="/workspace/sase",
            canonical_path="long/generated_skills.md",
            resolved_path="/workspace/sase/memory/generated_skills.md",
            agent_name="zoom.snapshot.agent",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/workspace/sase/artifacts/visual-zoom",
            reason="needed generated skill rules",
            byte_count=64,
            frontmatter_stripped=False,
        ),
        MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="visual-read-gotchas",
            timestamp="2026-06-14T14:18:30+00:00",
            project="visual",
            cwd="/workspace/sase",
            canonical_path="short/gotchas.md",
            resolved_path="/workspace/sase/memory/short/gotchas.md",
            agent_name="zoom.snapshot.agent",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/workspace/sase/artifacts/visual-zoom",
            reason="avoid the double-install gotcha",
            byte_count=64,
            frontmatter_stripped=True,
        ),
    ]


def _context_skill_uses() -> list[SkillUseEvent]:
    return [
        SkillUseEvent(
            schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
            id="visual-skill-plan",
            timestamp="2026-06-14T14:23:08+00:00",
            project="visual",
            cwd="/workspace/sase",
            skill_name="sase_plan",
            agent_name="zoom.snapshot.agent",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/workspace/sase/artifacts/visual-zoom",
            reason="needed an implementation plan",
            runtime="codex",
        )
    ]


async def test_agents_file_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_zoom_agent(tmp_path)])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("z")
        await page.expect_modal("ZoomPanelModal")
        await page.pause()
        await page.pause()

        ace_png_visual.assert_page_png(
            page,
            "agents_file_zoom_modal_120x40",
            title="ACE agents file zoom modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_context_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_zoom_agent(tmp_path)],
        memory_reads=_context_memory_reads(),
        skill_uses=_context_skill_uses(),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("p")
        await page.press("z")
        await page.expect_modal("ZoomPanelModal")
        await page.pause()
        await page.pause()

        _assert_page_svg_contains(page, "AGENT CONTEXT")
        _assert_page_svg_contains(page, "◇")
        _assert_page_svg_contains(page, "long/generated_skills.md")
        _assert_page_svg_contains(page, "◆")
        _assert_page_svg_contains(page, "sase_plan")
        ace_png_visual.assert_page_png(
            page,
            "agents_context_zoom_modal_120x40",
            title="ACE agents context zoom modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_metadata_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_zoom_agent(tmp_path, include_xprompts=True)],
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("p")
        await page.press("z")
        await page.expect_modal("ZoomPanelModal")
        await page.pause()
        await page.pause()

        ace_png_visual.assert_page_png(
            page,
            "agents_metadata_zoom_modal_120x40",
            title="ACE agents metadata zoom modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


def _done_agents() -> list[Agent]:
    """Three completed agents in the ``Done`` bucket.

    Used by the unread-highlight snapshot — all three rows are then
    marked unread post-startup so the Agents-tab info-panel header
    renders a non-zero ``N unread`` count that exercises the yellow
    background style.
    """
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            stop_time=datetime(2026, 5, 9, 10, 7, 30),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
            response_path="/workspace/sase/artifacts/visual-plan/response.md",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
        ),
    ]


async def test_agents_unread_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = _done_agents()
    patch_startup_loaders(monkeypatch, agents=done)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        identities = {agent.identity for agent in done}
        page.app._unread_completed_agent_ids = set(identities)
        page.app._manual_unread_agent_ids = set(identities)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app._update_agents_info_panel()
        from sase.ace.tui.widgets import AgentInfoPanel

        panel = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        assert panel._unread_count == 3, f"expected 3 unread, got {panel._unread_count}"
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_unread_highlight_120x40",
            title="ACE agents unread highlight",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_sibling_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=sibling_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)
        assert page.app._agent_sibling_index().sibling_count(page.app.current_idx) == 2
        _assert_page_svg_contains(page, "siblings: ")

        ace_png_visual.assert_page_png(
            page,
            "agents_sibling_badge_120x40",
            title="ACE agents sibling badge",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agent_sibling_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=sibling_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentSiblingModal")
        await wait_for_visual_idle(page)
        modal = page.app.screen_stack[-1]
        assert modal.__class__.__name__ == "AgentSiblingModal"
        choices = vars(modal)["_choices"]
        assert [choice.global_idx for choice in choices] == [1, 2]
        _assert_page_svg_contains(page, "Sibling Agents: visual family")
        _assert_page_svg_contains(page, "visual.code.implementation.with...")

        ace_png_visual.assert_page_png(
            page,
            "agent_sibling_modal_60x30",
            title="ACE agent sibling modal narrow",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
