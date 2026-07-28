"""Shared builders and render helpers for summary fold contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
    build_header_text,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import MemberJumpMap
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of

NOW = datetime(2026, 7, 19, 12, 0, 0)


@dataclass(frozen=True, slots=True)
class RenderedSummary:
    plain: str
    jump_map: MemberJumpMap


def single_jump_map(published: list[MemberJumpMap]) -> MemberJumpMap:
    assert len(published) == 1
    return published[0]


def make_family(
    tmp_path: Path,
    *,
    suffix: str,
    with_prompt_content: bool,
) -> Agent:
    family = f"fold-contract-{suffix}"
    started = NOW - timedelta(minutes=5)
    phases: list[Agent] = []
    for index, role in enumerate(("plan", "code")):
        artifacts = tmp_path / f"{suffix}-{role}"
        artifacts.mkdir()
        if with_prompt_content:
            (artifacts / "raw_xprompt.md").write_text(
                "\n".join(f"{role} xprompt line {line}" for line in range(1, 16))
                + "\n",
                encoding="utf-8",
            )
            (artifacts / "01_prompt.md").write_text(
                "\n".join(f"{role} prompt line {line}" for line in range(1, 16)) + "\n",
                encoding="utf-8",
            )
        response = artifacts / "response.md"
        response.write_text(f"{role} completed\n", encoding="utf-8")
        phase = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"{family}--{role}",
            project_file="/tmp/fold-contract.sase",
            status="DONE",
            start_time=started + timedelta(minutes=index * 2),
            run_start_time=started + timedelta(minutes=index * 2),
            stop_time=started + timedelta(minutes=(index + 1) * 2),
            raw_suffix=f"{suffix}-{role}",
            artifacts_dir=str(artifacts),
            response_path=str(response),
            agent_name=f"{family}--{role}",
            agent_family=family,
            agent_family_role=role,
            role_suffix=f"--{role}",
            plan_chain_root=role == "plan",
            model="gpt-5",
        )
        phases.append(phase)
    root, child = phases
    root.followup_agents = [child]
    assert root.is_family_container_row
    return root


def render_family(agent: Agent, level: FoldLevel) -> RenderedSummary:
    published: list[MemberJumpMap] = []
    header, error = build_header_text(
        agent,
        cheap=True,
        lane_fold_level=level,
        member_jump_map_publisher=published.append,
    )
    panel = FakePromptPanel()
    panel._update_family_display(
        agent,
        header,
        error,
        panel_level=level,
        section_fold_overrides={},
    )
    return RenderedSummary(
        plain=plain_of(panel.captured[-1]),
        jump_map=single_jump_map(published),
    )


def section_body(rendered: str, title: str) -> str:
    lines = rendered.splitlines()
    heading_index = next(
        index
        for index, line in enumerate(lines)
        if title in line and line.lstrip().startswith(("▸", "▾", "▼", "◆"))
    )
    body: list[str] = []
    for line in lines[heading_index + 1 :]:
        stripped = line.strip()
        if stripped and len(set(stripped)) == 1 and stripped[0] in {"─", "━"}:
            break
        body.append(line)
    return "\n".join(body).strip()


def heading_line(rendered: str, title: str) -> str:
    return next(
        line
        for line in rendered.splitlines()
        if title in line and line.lstrip().startswith(("▸", "▾", "▼", "◆"))
    )
