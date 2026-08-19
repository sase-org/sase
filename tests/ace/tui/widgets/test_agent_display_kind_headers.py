"""Kind-identity chrome on Agents-tab metadata documents."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from rich.style import Style as RichStyle
from rich.text import Text

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._helpers import append_kind_header
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_agent,
    plain_of,
)
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_kind_header
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot


def _section_ids(text: Text) -> list[str]:
    identities: list[str] = []
    for span in text.spans:
        style = span.style
        if not isinstance(style, RichStyle) or not style.meta:
            continue
        identity = style.meta.get(SECTION_MARKER_META_KEY)
        if isinstance(identity, str) and identity not in identities:
            identities.append(identity)
    return identities


def test_append_kind_header_does_not_mark_a_section() -> None:
    text = Text()
    append_kind_header(text, "AGENT SHELL", "#FFD700")

    assert text.plain == "AGENT SHELL\n"
    assert_kind_header(text, "AGENT SHELL", "#FFD700")
    assert _section_ids(text) == []


def test_family_container_header_opens_with_family_kind_line(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)

    cheap, _ = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
    )
    full, _ = build_header_text(
        root,
        cheap=False,
        lane_fold_level=FoldLevel.COLLAPSED,
    )

    for header in (cheap, full):
        assert_kind_header(header, "FAMILY", "#00AFFF", before="FAMILY MEMBERS")
        assert header.plain.startswith("FAMILY\nName:")
        assert header.plain.index("Name:") < header.plain.index("Fold:")
        assert header.plain.index("Fold:") < header.plain.index("FAMILY MEMBERS")
        assert "family" not in _section_ids(header)
        assert _section_ids(header)[0] == "members"


def test_family_member_header_opens_with_agent_shell(
    tmp_path: Path,
) -> None:
    _root, child = make_family(tmp_path)

    header, _ = build_header_text(
        child,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
    )

    assert_kind_header(header, "AGENT SHELL", "#FFD700")
    assert header.plain.startswith("AGENT SHELL\nName:")
    assert "FAMILY MEMBERS · 1 · alpha" in header.plain
    prefix, _, _ = header.plain.partition("FAMILY MEMBERS")
    assert "FAMILY\n" not in prefix
    assert "family" not in _section_ids(header)
    assert "agent-shell" not in _section_ids(header)
    assert _section_ids(header)[0] == "members"


def test_standalone_agent_header_opens_with_agent_shell() -> None:
    agent = make_agent(agent_name="solo")

    cheap, _ = build_header_text(agent, cheap=True)
    full, _ = build_header_text(agent, cheap=False)

    for header in (cheap, full):
        assert_kind_header(header, "AGENT SHELL", "#FFD700")
        assert header.plain.startswith("AGENT SHELL\nName: solo\n")
        assert "agent-shell" not in _section_ids(header)


def test_update_header_only_includes_kind_heading_on_first_paint() -> None:
    panel = FakePromptPanel()
    agent = make_agent(agent_name="solo")

    panel.update_header_only(agent)

    plain = plain_of(panel.captured[-1])
    assert plain.startswith("AGENT SHELL\nName: solo\n")


def test_unattached_family_root_opens_with_agent_shell() -> None:
    root = make_agent(
        agent_name="alpha--plan",
        agent_family="alpha",
        agent_family_role="root",
        plan_chain_root=True,
    )
    planner = make_agent(agent_name="alpha--plan-step")
    planner.is_synthetic_planner = True
    root.followup_agents = [planner]

    assert root.is_family_container_row is False
    assert root.is_agent_entry is True

    header, _ = build_header_text(root, cheap=True)

    assert_kind_header(header, "AGENT SHELL", "#FFD700")
    assert not header.plain.startswith("FAMILY\n")


def test_monitor_member_has_no_kind_heading() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-row",
        project_file="/tmp/monitor.sase",
        status="MONITORING",
        start_time=started,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m123abc456def",
        monitor_state="running",
    )

    assert agent.is_monitor is True
    assert agent.is_agent_entry is False

    header, _ = build_header_text(agent, cheap=True)

    assert not header.plain.startswith("AGENT SHELL")
    assert not header.plain.startswith("FAMILY")
    assert header.plain.startswith("Name:")


@pytest.mark.parametrize("step_type", ["bash", "python", "parallel"])
def test_workflow_step_has_no_kind_heading(step_type: str) -> None:
    agent = make_agent(
        agent_type=AgentType.WORKFLOW,
        parent_workflow="wf",
        step_name="do",
        step_type=step_type,
        step_index=0,
        total_steps=2,
    )

    assert agent.is_agent_entry is False

    header, _ = build_header_text(agent, cheap=True)

    assert not header.plain.startswith("AGENT SHELL")
    assert not header.plain.startswith("FAMILY")
    assert "Step: do\n" in header.plain


def test_workflow_agent_step_opens_with_agent_shell() -> None:
    agent = make_agent(
        agent_type=AgentType.WORKFLOW,
        parent_workflow="wf",
        step_name="write",
        step_type="agent",
        step_index=1,
        total_steps=2,
    )

    assert agent.is_agent_entry is True

    header, _ = build_header_text(agent, cheap=True)

    assert_kind_header(header, "AGENT SHELL", "#FFD700")


def test_clan_header_still_opens_with_clan() -> None:
    member = make_clan_agent(
        "research.only",
        status="WAITING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    container = project_clan_tree([member])[0]

    header, _ = build_header_text(container, cheap=True)

    assert_kind_header(header, "CLAN", "#D75FFF")
    assert header.plain.startswith("CLAN\nName: research\n")


def test_tribe_header_still_opens_with_tribe() -> None:
    detail = build_tribe_detail_text(make_tribe_snapshot())

    assert_kind_header(detail, "TRIBE", "#FFD75F")
    assert detail.plain.startswith("TRIBE\nName:")
