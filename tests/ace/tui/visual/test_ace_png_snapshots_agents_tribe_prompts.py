"""ACE PNG snapshots for the tribe PROMPTS intent map."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.monitor_state import monitor_state_bucket
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
    prompt_header_and_body_text,
    scroll_main_section_to_top,
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

_AGENT_SESSION_NAME = "visual-prompts-build"
_STARTED = datetime(2026, 7, 18, 14, 0, 0)


def _write_xprompt(directory: Path, raw: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw_xprompt.md").write_text(raw, encoding="utf-8")


def _tribe_prompt_agents(tmp_path: Path) -> list[Agent]:
    plan_dir = tmp_path / "prompts-plan"
    _write_xprompt(
        plan_dir,
        "%id(3, tribe=epic)\n"
        "%model:@medium\n"
        "@plan:202609/tribe_prompts.md The above plan has been reviewed and "
        "approved. Implement it now.\n",
    )
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-prompts-build--plan",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=_STARTED,
        run_start_time=_STARTED,
        raw_suffix="visual-prompts-plan",
        artifacts_dir=str(plan_dir),
        agent_name=f"{_AGENT_SESSION_NAME}--plan",
        agent_session=_AGENT_SESSION_NAME,
        agent_session_role="root",
        role_suffix="--plan",
        plan_chain_root=True,
        model="gpt-5",
        tribe="epic",
    )
    code_dir = tmp_path / "prompts-code"
    _write_xprompt(
        code_dir,
        "%id(4, tribe=epic)\n#bd/work_phase_bead:sase-16t.2\n",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-prompts-build--code",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=_STARTED,
        run_start_time=_STARTED,
        raw_suffix="visual-prompts-code",
        parent_timestamp=root.raw_suffix,
        artifacts_dir=str(code_dir),
        agent_name=f"{_AGENT_SESSION_NAME}--code",
        agent_session=_AGENT_SESSION_NAME,
        agent_session_role="code",
        role_suffix="--code",
        model="gpt-5",
        activity="waiting for verification",
        tribe="epic",
    )
    root.followup_agents = [child]
    rows = [root, child]
    for suffix, bead in (("one", "sase-16t.1"), ("two", "sase-16t.2")):
        member_dir = tmp_path / f"prompts-clan-{suffix}"
        _write_xprompt(member_dir, f"#bd/work_phase_bead:{bead}\n")
        rows.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name=f"visual-prompts-clan-{suffix}",
                project_file="/workspace/sase/visual_project.sase",
                status="RUNNING",
                start_time=_STARTED,
                run_start_time=_STARTED,
                raw_suffix=f"visual-prompts-clan-{suffix}",
                artifacts_dir=str(member_dir),
                agent_name=f"visual-prompts-clan.{suffix}",
                agent_clan="visual-prompts-clan",
                agent_clan_generation="gen-1",
                model="gpt-5",
                tribe="epic",
            )
        )
    for slug, preamble in (
        ("first", "%id(5, tribe=epic)\n"),
        ("second", "%id(6, tribe=epic)\n%wait:30\n"),
    ):
        standalone_dir = tmp_path / f"prompts-{slug}"
        _write_xprompt(
            standalone_dir,
            f"{preamble}Inspect the documentation changes made by the update "
            "agent for sase.\n",
        )
        rows.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name=f"visual-prompts-{slug}",
                project_file="/workspace/sase/visual_project.sase",
                status="DONE",
                start_time=_STARTED,
                run_start_time=_STARTED,
                stop_time=_STARTED,
                raw_suffix=f"visual-prompts-{slug}",
                artifacts_dir=str(standalone_dir),
                agent_name=f"visual-prompts-{slug}",
                model="gpt-5",
                tribe="epic",
            )
        )
    mon_dir = tmp_path / "prompts-monitor"
    _write_xprompt(
        mon_dir,
        "%xprompts_enabled:false\n# Monitored command finished\nAll checks passed.\n",
    )
    mon_started = datetime(2026, 7, 18, 14, 10, 0)
    rows.append(
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-prompts-mon",
            project_file="/workspace/sase/visual_project.sase",
            status="MONITORED",
            status_bucket=monitor_state_bucket("completed"),
            start_time=mon_started,
            stop_time=mon_started,
            raw_suffix="visual-prompts-mon",
            parent_timestamp=child.raw_suffix,
            artifacts_dir=str(mon_dir),
            role_suffix="--mon",
            agent_name=f"{_AGENT_SESSION_NAME}--mon",
            agent_session=_AGENT_SESSION_NAME,
            agent_session_role="monitor",
            monitor_id="gh6fddk5v3g9",
            monitor_state="completed",
            monitor_label="just check",
            monitor_command="just check",
            monitor_cwd="/workspace/sase",
            monitor_reason="Full-suite verification before landing",
            monitor_exit_code=0,
            tribe="epic",
        )
    )
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


async def _jump_to_prompts(page: AcePage) -> None:
    """Scroll the Summary card's PROMPTS section to the deck top."""
    await scroll_main_section_to_top(page, "tribe:prompts")


async def test_tribe_panel_prompts_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 15, 0, 0))
    patch_startup_loaders(monkeypatch, agents=_tribe_prompt_agents(tmp_path))

    async with AcePage(query='"visual-prompts"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        await page.press("J")
        assert page.app._panel_group.focused_key == "epic"
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await page.wait_for(
            lambda _screen: "PROMPTS" in prompt_header_and_body_text(panel),
            timeout=30.0,
        )
        assert page.app._member_jump_maps[("panel", "epic")].targets

        await _jump_to_prompts(page)
        await wait_for_svg_contains(page, "PROMPTS")
        ace_png_visual.assert_page_png(
            page,
            "agents_tribe_panel_prompts_glance_120x40",
            title="ACE tribe panel prompts glance",
        )

        await page.press("z", "3")
        assert page.app.panel_fold_level.value == "fully_expanded"
        await _jump_to_prompts(page)
        await wait_for_svg_contains(page, "PROMPTS")
        ace_png_visual.assert_page_png(
            page,
            "agents_tribe_panel_prompts_inspect_120x40",
            title="ACE tribe panel prompts inspect",
        )
