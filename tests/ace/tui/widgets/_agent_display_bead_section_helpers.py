"""Shared builders and render helpers for Agents-tab BEAD lane tests."""

from __future__ import annotations

from datetime import datetime
from io import StringIO

import pytest
from rich.console import Console

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_associated_plan import PhaseBeadSummary
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_bead_section import (
    BEAD_FIELD_LABEL_WIDTH,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import AgentHeader
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_header_text,
)
from sase.phase_size_presentation import PhaseSizeValue
from tests.ace.tui.widgets._agent_display_helpers import make_agent

CREATED_AT = "2026-08-01T14:30:00Z"
CREATED_LABEL = "2026-08-01 10:30:00 EDT · 4d ago"


@pytest.fixture(autouse=True)
def pin_bead_created_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze the clock so ``Created:`` renders a stable relative label."""
    monkeypatch.setattr(
        "sase.core.time.local_now",
        lambda: datetime(2026, 8, 5, 12, 0, 0),
    )


def bead_summary(
    *,
    bead_id: str = "sase-42.3",
    description: str | None = "Render only this selected phase.",
    actual_path: str | None = "/tmp/workspace/sase/repos/plans/202607/epic plan.md",
    display_path: str | None = "sase/repos/plans/202607/epic plan.md",
    exists: bool = True,
    readable: bool = True,
    phase_title: str | None = "Responsive BEAD lane",
    epic_title: str | None = "Phase bead context lane",
    size: PhaseSizeValue | None = "medium",
    notes: str | None = None,
    created_at: str = CREATED_AT,
) -> PhaseBeadSummary:
    return PhaseBeadSummary(
        id=bead_id,
        phase_title=phase_title,
        description=description,
        actual_plan_path=actual_path,
        display_plan_path=display_path,
        plan_exists=exists,
        plan_readable=readable,
        epic_title=epic_title,
        size=size,
        created_at=created_at,
        notes=notes,
    )


def bead_header(
    summary: PhaseBeadSummary,
    *,
    agent: Agent | None = None,
    lane_fold_level: FoldLevel | None = None,
    lane_section_fold_overrides: dict[str, FoldLevel] | None = None,
) -> AgentHeader:
    display_agent = agent or make_agent(
        agent_name="worker",
        phase_bead_id=summary.id,
        epic_bead_id=summary.id.rsplit(".", maxsplit=1)[0],
    )
    header, _ = build_header_text(
        display_agent,
        summary=DetailHeaderSummary(phase_bead=summary),
        lane_fold_level=lane_fold_level,
        lane_section_fold_overrides=lane_section_fold_overrides,
    )
    return header


def render_bead_header(header: AgentHeader, *, width: int) -> list[str]:
    output = StringIO()
    console = Console(file=output, width=width, color_system=None)
    console.print(header, end="")
    return output.getvalue().splitlines()


def bead_field_lines(header: AgentHeader, label: str, *, width: int) -> list[str]:
    lines = render_bead_header(header, width=width)
    start = next(
        index
        for index, line in enumerate(lines)
        if line[:BEAD_FIELD_LABEL_WIDTH].strip() == f"{label}:"
    )
    result = [lines[start]]
    prefix = " " * BEAD_FIELD_LABEL_WIDTH
    for line in lines[start + 1 :]:
        if not line.startswith(prefix):
            break
        result.append(line)
    return result


def reconstruct_field_value(lines: list[str], *, spaced: bool) -> str:
    values = [line[BEAD_FIELD_LABEL_WIDTH:].rstrip() for line in lines]
    return (" " if spaced else "").join(values)


def bead_field_labels(header: AgentHeader) -> list[str]:
    known_labels = {
        "Phase Title:",
        "Flag Title:",
        "Task Title:",
        "Description:",
        "Notes:",
        "Epic Plan:",
        "Epic Title:",
        "Flag Key:",
        "Remove By:",
        "Size:",
        "+1 Reports:",
        "+1 Evidence:",
        "Created:",
    }
    return [
        label
        for line in header.plain.splitlines()
        if (label := line[:BEAD_FIELD_LABEL_WIDTH].strip()) in known_labels
    ]


def family_container_agent() -> Agent:
    child = make_agent(
        agent_name="worker--code",
        agent_family="worker",
        agent_family_role="member",
    )
    root = make_agent(
        agent_name="worker--plan",
        agent_family="worker",
        agent_family_role="root",
        followup_agents=[child],
    )
    child.family_container = root
    return root
