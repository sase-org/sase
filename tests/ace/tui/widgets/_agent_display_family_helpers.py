"""Shared helpers for family-container detail panel tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType


def make_family(
    tmp_path: Path,
    *,
    in_clan: bool = False,
) -> tuple[Agent, Agent]:
    started = datetime(2026, 7, 18, 12, 0, 0)
    root_dir = tmp_path / ("clan-plan" if in_clan else "standalone-plan")
    child_dir = tmp_path / ("clan-code" if in_clan else "standalone-code")
    root_dir.mkdir()
    child_dir.mkdir()
    write_phase_content(root_dir, "plan")
    write_phase_content(child_dir, "code")

    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family-test",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started,
        stop_time=started + timedelta(minutes=2),
        raw_suffix="20260718120000",
        artifacts_dir=str(root_dir),
        response_path=str(root_dir / "response.md"),
        agent_name="alpha--plan",
        agent_family="alpha",
        agent_family_role="plan",
        role_suffix="--plan",
        plan_chain_root=True,
        model="claude/opus",
        agent_clan="map" if in_clan else None,
        output_variables={"plan_path": "/tmp/plan.md"},
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family-test",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=started + timedelta(minutes=2),
        stop_time=started + timedelta(minutes=5),
        raw_suffix="20260718120200",
        artifacts_dir=str(child_dir),
        response_path=str(child_dir / "response.md"),
        agent_name="alpha--code",
        agent_family="alpha",
        agent_family_role="code",
        role_suffix="--code",
        model="claude/sonnet",
        agent_clan="map" if in_clan else None,
        output_variables={"code_path": "/tmp/code.md"},
    )
    root.followup_agents = [child]
    assert root.is_family_container_row is True
    return root, child


def write_phase_content(directory: Path, role: str) -> None:
    (directory / "raw_xprompt.md").write_text(
        "\n".join(f"{role} xprompt line {index}" for index in range(1, 16)) + "\n",
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
