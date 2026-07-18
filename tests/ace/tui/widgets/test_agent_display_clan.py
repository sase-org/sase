"""Aggregate clan detail rendering in the Agents metadata panel."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_render import (
    AgentDisplayRenderMixin,
)

_GENERATION = "20260717120000"


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def _agent(
    name: str,
    *,
    status: str,
    start: datetime,
    stop: datetime | None = None,
    model: str | None = "gpt-5",
    parent_timestamp: str | None = None,
    family: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status=status,
        start_time=start,
        run_start_time=start,
        stop_time=stop,
        raw_suffix=start.strftime("%Y%m%d%H%M%S") + name,
        agent_name=name,
        parent_timestamp=parent_timestamp,
        agent_family=family,
        agent_clan="research",
        agent_clan_generation=_GENERATION,
        model=model,
    )


def test_clan_header_rolls_up_identity_counts_runtime_and_launch_order() -> None:
    first = _agent(
        "research.first",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    second = _agent(
        "research.second",
        status="FAILED",
        start=datetime(2026, 7, 17, 12, 1, 0),
        stop=datetime(2026, 7, 17, 12, 1, 45),
        model=None,
    )
    container = project_clan_tree([second, first])[0]
    container.clan_tags = ("epic", "review")

    detail = build_clan_detail_text(
        container,
        now=datetime(2026, 7, 17, 12, 4, 0),
    )

    header, members = detail.plain.split("\n" + "─" * 50 + "\n", 1)
    assert header.strip() == (
        "◫ CLAN\n"
        "Name: research\n"
        "Tribes: @epic @review\n"
        "Status: FAILED [F1 D1]\n"
        "Runtime: 2m\n"
        "Members: 2 agents · 0 families"
    )
    assert members.strip() == (
        "MEMBERS · 2\n"
        ".first · agent · ✓ DONE · gpt-5 · 2m\n"
        ".second · agent · ✗ FAILED · default · 45s"
    )
    assert _style_at(detail, detail.plain.index("◫")) == ("bold #D75FFF underline")
    assert _style_at(detail, detail.plain.index("research")) == "#D75FFF"


def test_family_header_recolors_only_real_container_name() -> None:
    family = _agent(
        "research.writer",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
        family="research.writer",
    )
    family.agent_clan = None
    family.agent_family_role = "root"
    family.refresh_presented_agent_name()
    synthetic = _agent(
        "research.writer--plan",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 1, 0),
        family="research.writer",
    )
    synthetic.is_synthetic_planner = True
    family.followup_agents = [synthetic]

    lone_header, _ = build_header_text(family, cheap=True)

    assert isinstance(lone_header, Text)
    assert _style_at(lone_header, lone_header.plain.index("research.writer")) == (
        "#FFD700"
    )

    member = _agent(
        "research.writer--code",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 2, 0),
        family="research.writer",
    )
    family.followup_agents.append(member)

    family_header, _ = build_header_text(family, cheap=True)

    assert isinstance(family_header, Text)
    assert (
        _style_at(
            family_header,
            family_header.plain.index("research.writer"),
        )
        == "#00AFFF"
    )

    ordinary = _agent(
        "research.reader",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 3, 0),
    )
    ordinary.agent_clan = None
    ordinary_header, _ = build_header_text(ordinary, cheap=True)

    assert isinstance(ordinary_header, Text)
    assert (
        _style_at(
            ordinary_header,
            ordinary_header.plain.index("research.reader"),
        )
        == "#FFD700"
    )


def test_clan_header_uses_same_unread_aggregate_as_list_row() -> None:
    read = _agent(
        "research.read",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 1, 0),
    )
    unread = _agent(
        "research.unread",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 1, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    container = project_clan_tree([read, unread])[0]

    detail = build_clan_detail_text(
        container,
        unread_ids={unread.identity},
    )

    assert "Status: DONE [U1 D1]\n" in detail.plain


def test_clan_members_render_family_aggregate_and_every_member() -> None:
    family_name = "research.writer"
    planner = _agent(
        f"{family_name}--plan-0",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 1, 0),
        family=family_name,
    )
    coder = _agent(
        f"{family_name}--code",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 2, 0),
        stop=datetime(2026, 7, 17, 12, 3, 0),
        model="sonnet",
        parent_timestamp=planner.raw_suffix,
        family=family_name,
    )
    planner.runtime_children = [coder]
    container = project_clan_tree([planner, coder])[0]

    detail = build_clan_detail_text(
        container,
        now=datetime(2026, 7, 17, 12, 4, 0),
    )

    assert "Members: 2 agents · 1 family\n" in detail.plain
    assert detail.plain.split("MEMBERS · 1\n", 1)[1] == (
        ".writer · family · ✓ DONE · mixed · 2m\n"
        "  ├─ --plan-0 · agent · ✓ DONE · gpt-5 · 1m\n"
        "  └─ --code · agent · ✓ DONE · sonnet · 1m\n"
    )


def test_clan_build_header_path_is_aggregate_only() -> None:
    member = _agent(
        "research.only",
        status="WAITING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.run_start_time = None
    container = project_clan_tree([member])[0]

    header, traceback = build_header_text(container, cheap=True)

    assert traceback is None
    assert header.plain.startswith("◫ CLAN\nName: research\n")
    assert "AGENT PROMPT" not in header.plain
    assert "ChangeSpec:" not in header.plain
    assert "No prompt file found" not in header.plain


def test_non_clan_agent_has_no_members_section() -> None:
    agent = _agent(
        "research.only",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )

    header, _ = build_header_text(agent, cheap=True)

    assert not header.plain.startswith("◫ CLAN")
    assert "MEMBERS" not in header.plain


def test_legacy_parallel_root_keeps_compatibility_members_section() -> None:
    root = _agent(
        "legacy-root",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    root.agent_clan = None
    root.agent_family_parallel = True
    child = _agent(
        "legacy-child",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 1, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    child.agent_clan = None
    child.agent_family_parallel = True
    child.agent_family_role = "phase"
    root.runtime_children = [child]

    header, _ = build_header_text(root, cheap=True)

    assert "MEMBERS · 1\n" in header.plain
    assert "phase · legacy-child · ✓ DONE · gpt-5 · 1m0s\n" in header.plain


def test_clan_full_render_bypasses_attempt_and_artifact_paths() -> None:
    member = _agent(
        "research.only",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 1, 0),
    )
    container = project_clan_tree([member])[0]

    class _Harness(AgentDisplayRenderMixin):
        attempt_pinned_number = 4

        def __init__(self) -> None:
            self.content = None

        def update(self, content: object) -> None:
            self.content = content

        def _render_attempt_pinned(self, *_args: object) -> None:
            raise AssertionError("synthetic clans have no attempts")

    harness = _Harness()
    harness._update_display_impl(container)

    assert isinstance(harness.content, Text)
    assert harness.content.plain.startswith("◫ CLAN\nName: research\n")
