"""ACE PNG snapshots for fold-aware family detail panels and member jumps."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets import AgentList
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_FAMILY_NAME = "visual-family"
_STARTED = datetime(2026, 7, 18, 13, 0, 0)


def _write_phase_content(directory: Path, role: str) -> None:
    directory.mkdir()
    (directory / "raw_xprompt.md").write_text(
        "\n".join(f"#{role} family xprompt line {index}" for index in range(1, 16))
        + "\n",
        encoding="utf-8",
    )
    (directory / "01_prompt.md").write_text(
        "\n".join(f"{role} prompt line {index}" for index in range(1, 16)) + "\n",
        encoding="utf-8",
    )
    (directory / "response.md").write_text(
        "\n".join(f"{role} reply line {index}" for index in range(1, 7)) + "\n",
        encoding="utf-8",
    )


def _family_agents(
    tmp_path: Path,
    *,
    member_count: int,
    with_content: bool,
    with_monitor: bool = False,
    monitor_command: str = "just check-full",
    monitor_reason: str = "Full-suite verification before landing",
) -> list[Agent]:
    assert member_count >= 2
    root_dir = tmp_path / "family-plan"
    if with_content:
        _write_phase_content(root_dir, "plan")
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-family-root",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=_STARTED,
        stop_time=_STARTED + timedelta(minutes=2),
        raw_suffix="20260718130000-family-plan",
        artifacts_dir=str(root_dir) if with_content else None,
        response_path=str(root_dir / "response.md") if with_content else None,
        role_suffix="--plan",
        agent_name=f"{_FAMILY_NAME}--plan",
        agent_family=_FAMILY_NAME,
        agent_family_role="plan",
        plan_chain_root=True,
        output_variables={"plan_path": "/workspace/sase/plans/family.md"},
        workspace_num=4,
        llm_provider="claude",
        model="opus",
    )
    rows = [root]
    for index in range(1, member_count):
        role = "code" if index == 1 else ("reviewer" if index == 2 else "phase")
        suffix = f"--{role}" if index < 3 else f"--phase-{index:02d}"
        phase_dir = tmp_path / f"family-{index:02d}"
        if with_content:
            _write_phase_content(phase_dir, role)
        started = _STARTED + timedelta(minutes=index * 2)
        rows.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name=f"visual-family-{index:02d}",
                project_file="/workspace/sase/visual_project.sase",
                status="DONE",
                start_time=started,
                stop_time=started + timedelta(minutes=2),
                raw_suffix=f"2026071813{index * 2:02d}00-family-{index:02d}",
                parent_timestamp=root.raw_suffix,
                artifacts_dir=str(phase_dir) if with_content else None,
                response_path=(
                    str(phase_dir / "response.md") if with_content else None
                ),
                role_suffix=suffix,
                agent_name=f"{_FAMILY_NAME}{suffix}",
                agent_family=_FAMILY_NAME,
                agent_family_role=role,
                activity=(
                    "implementing numbered navigation"
                    if index == 1
                    else "reviewing fold alignment"
                ),
                output_variables={
                    f"phase_{index}_report": f"/workspace/sase/out/phase-{index}.md"
                },
                workspace_num=4 + index,
                llm_provider="codex",
                model="gpt-5",
            )
        )
    if with_monitor:
        mon_dir = tmp_path / "family-monitor"
        mon_dir.mkdir()
        (mon_dir / "live_reply.md").write_text(
            "✓ lint (ruff)\nFAILED tests/ace/tui/test_x.py::test_y\n",
            encoding="utf-8",
        )
        mon_started = _STARTED + timedelta(minutes=member_count * 2)
        rows.append(
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="visual-family-mon",
                project_file="/workspace/sase/visual_project.sase",
                status="MONITORED",
                start_time=mon_started,
                stop_time=mon_started + timedelta(minutes=1),
                raw_suffix="20260718131200-family-mon",
                parent_timestamp=root.raw_suffix,
                artifacts_dir=str(mon_dir),
                role_suffix="--mon",
                agent_name=f"{_FAMILY_NAME}--mon",
                agent_family=_FAMILY_NAME,
                agent_family_role="monitor",
                monitor_id="gh6fddk5v3g9",
                monitor_state="completed",
                monitor_start_status="MONITORING",
                monitor_stop_status="MONITORED",
                monitor_command=monitor_command,
                monitor_cwd="/workspace/sase",
                monitor_reason=monitor_reason,
                monitor_next_action="Report pass/fail to the user.",
                monitor_exit_code=1,
                monitor_timeout_seconds=2700.0,
                workspace_num=4 + member_count,
            )
        )
    _apply_status_overrides(rows)
    return sort_and_reorder(rows, [])


async def test_family_panel_fold_levels_and_member_override_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(tmp_path, member_count=3, with_content=True),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        container_identity = container.identity
        assert container.is_family_container_row is True
        assert len(page.app._member_jump_maps[container_identity].targets) == 3
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_level_1_120x40",
            title="ACE family panel fold level 1",
        )

        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        for _ in range(20):
            await page.press("ctrl+j")
            if panel.active_section_identity == "agent-xprompt":
                break
        assert panel.active_section_identity == "agent-xprompt"
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_family_conversation_level_1_120x40",
            title="ACE family conversation at fold level 1",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.FULLY_EXPANDED
        await wait_for_visual_idle(page)
        assert panel.active_section_identity == "agent-xprompt"
        ace_png_visual.assert_page_png(
            page,
            "agents_family_conversation_level_2_120x40",
            title="ACE family conversation at fold level 2",
        )
        for _ in range(20):
            if panel.active_section_identity is None:
                break
            await page.press("ctrl+j")
        assert panel.active_section_identity is None
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_level_2_120x40",
            title="ACE family panel fold level 2",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.EXPANDED
        await wait_for_visual_idle(page)
        assert panel.active_section_identity is None
        await page.press("ctrl+j")
        assert panel.active_section_identity == "members"
        await page.press("ctrl+j")
        assert panel.active_section_identity == f"member:{_FAMILY_NAME}--plan"
        await page.press("ctrl+j")
        assert panel.active_section_identity == f"member:{_FAMILY_NAME}--code"
        await page.press("z", "a")
        assert (
            page.app._panel_fold_overrides.get_override(f"member:{_FAMILY_NAME}--code")
            is FoldLevel.FULLY_EXPANDED
        )
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_member_override_120x40",
            title="ACE family panel member override",
        )

        await page.press("1")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_FAMILY_NAME}--code"
            )
        )
        await page.press("apostrophe", "apostrophe")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].identity == container_identity
            )
        )


async def test_family_member_panel_shows_sibling_roster_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(tmp_path, member_count=3, with_content=False),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True

        await page.press("1")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_FAMILY_NAME}--code"
            )
        )
        member = page.app._agents[page.app.current_idx]
        assert member.is_family_container_row is False
        await wait_for_visual_idle(page)

        member_jump_map = page.app._member_jump_maps[member.identity]
        member_targets = {target.member_identity for target in member_jump_map.targets}
        assert member.identity not in member_targets

        assert_page_svg_contains(page, "FAMILY MEMBERS")
        assert_page_svg_contains(page, "AGENT SHELL")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_member_roster_120x40",
            title="ACE family member panel roster",
        )


async def test_family_two_digit_roster_and_pending_footer_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 30, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(tmp_path, member_count=11, with_content=False),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        container_identity = container.identity
        jump_map = page.app._member_jump_maps[container_identity]
        assert jump_map.targets[0].number == "00"
        assert jump_map.targets[-1].number == "10"
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_two_digit_roster_120x40",
            title="ACE family panel two-digit roster",
        )

        await page.press("1")
        assert page.app._member_jump_pending_digit == "1"
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "member 1▁")
        assert_page_svg_contains(page, "second digit")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_pending_digit_120x40",
            title="ACE family panel pending member digit",
        )

        await page.press("0")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_FAMILY_NAME}--phase-10"
            )
        )
        await page.press("apostrophe", "apostrophe")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].identity == container_identity
            )
        )


async def test_family_panel_shells_monitor_metadata_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(
            tmp_path,
            member_count=2,
            with_content=False,
            with_monitor=True,
            monitor_command=(
                "just check-full --include visual --include slow "
                "--include every-family-shell-metadata-case"
            ),
            monitor_reason=(
                "Full-suite verification before landing the family shell "
                "metadata renderer"
            ),
        ),
    )

    async with AcePage(
        query='"visual-family"',
        size=(120, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True
        assert_page_svg_contains(page, "Shells:")
        assert_page_svg_contains(page, "⚙")
        assert_page_svg_contains(page, "why")
        assert_page_svg_contains(page, "Full-suite")
        assert_page_svg_contains(page, "verification")
        assert_page_svg_contains(page, "FAMILY MEMBERS")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_shells_monitor_120x40",
            title="ACE family panel shell metadata with monitor",
        )


async def test_family_conversation_monitor_phase_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(
            tmp_path,
            member_count=2,
            with_content=False,
            with_monitor=True,
        ),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        for _ in range(20):
            await page.press("ctrl+j")
            if panel.active_section_identity == "agent-reply":
                break
        assert panel.active_section_identity == "agent-reply"
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "MONITOR")
        assert_page_svg_contains(page, "just check-full")
        panel = page.app.query_one("#agent-list-panel", AgentList)
        assert "⚙1" in Text.from_markup(panel.border_title).plain
        ace_png_visual.assert_page_png(
            page,
            "agents_family_conversation_monitor_120x40",
            title="ACE family conversation with monitor phase",
        )
