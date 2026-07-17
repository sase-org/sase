"""Parallel-family member summaries in the agent metadata panel."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text


def _agent(
    name: str,
    *,
    status: str,
    start: datetime,
    stop: datetime | None = None,
    role: str = "phase",
    model: str | None = "gpt-5",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status=status,
        start_time=start,
        stop_time=stop,
        raw_suffix=start.strftime("%Y%m%d%H%M%S"),
        agent_name=name,
        agent_family="family-root",
        agent_family_role=role,
        agent_family_parallel=True,
        model=model,
    )


def test_family_root_header_snapshots_members_in_launch_order() -> None:
    root = _agent(
        "family-root",
        status="DONE",
        start=datetime(2026, 7, 16, 12, 0, 0),
        stop=datetime(2026, 7, 16, 12, 4, 0),
        role="root",
    )
    later = _agent(
        "family.phase-b",
        status="FAILED",
        start=datetime(2026, 7, 16, 12, 2, 0),
        stop=datetime(2026, 7, 16, 12, 2, 45),
        role="reviewer",
        model=None,
    )
    earlier = _agent(
        "family.phase-a",
        status="DONE",
        start=datetime(2026, 7, 16, 12, 1, 0),
        stop=datetime(2026, 7, 16, 12, 3, 0),
    )
    root.runtime_children = [later, earlier]

    header, _ = build_header_text(root, cheap=True)
    members_snapshot = header.plain.split("MEMBERS · 2\n", 1)[1].split(
        "\n\n" + "─" * 50,
        1,
    )[0]

    assert members_snapshot == (
        "phase · family.phase-a · ✓ DONE · gpt-5 · 2m0s\n"
        "reviewer · family.phase-b · ✗ FAILED · default · 45s"
    )


def test_non_root_or_serial_family_header_has_no_members_section() -> None:
    agent = _agent(
        "family.phase-a",
        status="RUNNING",
        start=datetime(2026, 7, 16, 12, 1, 0),
    )
    serial_child = _agent(
        "serial-child",
        status="DONE",
        start=datetime(2026, 7, 16, 12, 2, 0),
        stop=datetime(2026, 7, 16, 12, 3, 0),
    )
    serial_child.agent_family_parallel = False
    agent.runtime_children = [serial_child]

    header, _ = build_header_text(agent, cheap=True)

    assert "MEMBERS" not in header.plain
