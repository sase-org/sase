"""ACE PNG coverage for agent-metadata xprompt syntax highlighting."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_SKILL_ENTRY = XPromptAssistEntry(
    name="sase_plan",
    insertion="#sase_plan",
    reference_prefix="#",
    kind="xprompt",
    input_signature=None,
    inputs=(),
    content_preview=None,
    description="Create an implementation plan",
    is_skill=True,
)


def _xprompt_highlight_agent(artifacts_dir: Path) -> Agent:
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text(
        "#git:sase %auto #pr:my_change %m:opus\n---\n%{fast=a | safe=b} /sase_plan",
        encoding="utf-8",
    )
    (artifacts_dir / "01_prompt.md").write_text(
        "Implement the approved metadata-panel highlighting plan.\n",
        encoding="utf-8",
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-xprompt-highlight",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 16, 15, 30, 0),
        raw_suffix="20260716153000",
        agent_name="visual.xprompt-highlight",
        artifacts_dir=str(artifacts_dir),
    )


async def test_agents_xprompt_panel_highlighting_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = _xprompt_highlight_agent(tmp_path / "xprompt-highlight-artifacts")
    patch_startup_loaders(monkeypatch, agents=[agent])

    def _entries(
        _app: AceApp,
        _project: str | None,
        *,
        schedule: bool = True,
    ) -> list[XPromptAssistEntry]:
        del schedule
        return [_SKILL_ENTRY]

    monkeypatch.setattr(AceApp, "get_prompt_catalog_assist_entries", _entries)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "AGENT XPROMPT")
        await wait_for_svg_contains(page, "/sase_plan")
        await wait_for_visual_idle(page)

        for token in (
            "#git",
            ":sase",
            "%auto",
            "#pr",
            ":my_change",
            "%m",
            ":opus",
            "---",
            "/sase_plan",
        ):
            assert_page_svg_contains(page, token)
        ace_png_visual.assert_page_png(
            page,
            "agents_xprompt_panel_highlighting_120x40",
            title="ACE agents xprompt panel highlighting",
        )
