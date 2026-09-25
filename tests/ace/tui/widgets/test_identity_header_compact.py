"""Two-row compact identity lines for prompt-panel documents."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.fold_scale import AGENT_SESSION_FOLD_SCALE
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from sase.ace.tui.models._agent_clan import clan_member_counts
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.fold_scale import CLAN_FOLD_SCALE
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_identity import (
    build_clan_compact_lines,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_roster import (
    family_children,
    family_rows,
    ordered_clan_members,
)
from sase.ace.tui.widgets.prompt_panel._identity_header_compact import (
    build_agent_compact_lines,
    build_tribe_compact_lines,
    build_workflow_compact_lines,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent
from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    make_agent_session,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot


def _rows(agent_compact: object) -> tuple[str, str]:
    assert hasattr(agent_compact, "plain")
    lines = agent_compact.plain.splitlines()  # type: ignore[union-attr]
    assert len(lines) == 2
    return lines[0], lines[1]


def test_agent_rows_carry_name_model_and_state(tmp_path: Path) -> None:
    del tmp_path
    agent = make_agent(
        agent_name="solo",
        model="claude/opus",
        llm_provider="claude",
        reasoning_effort="xhigh",
        activity="writing",
        retry_count=1,
        max_retries=3,
    )
    summary = DetailHeaderSummary(
        xprompts_used=[
            {"kind": "part", "name": "review"},
            {"kind": "workflow", "name": "ship"},
            {"kind": "swarm", "name": "crew"},
            {"kind": "part", "name": "extra"},
        ]
    )
    compact = build_agent_compact_lines(agent=agent, summary=summary)
    assert compact.no_wrap is True
    assert compact.overflow == "ellipsis"
    first, second = _rows(compact)
    assert "solo" in first
    assert "CLAUDE(opus)" in first
    assert "xhigh" in first
    assert "▣ #review" in second
    assert "⌘ #ship" in second
    assert "+1" in second
    assert "↻ 1/3" in second
    assert "writing" in second


def test_agent_rows_show_auto_and_machine_chips() -> None:
    agent = make_agent(
        agent_name="solo",
        approve=True,
        auto_approve_plan_action="epic",
        fleet_origin_alias="gpu-box",
        fleet_diagnostic="feed stale",
    )
    first, second = _rows(build_agent_compact_lines(agent=agent))
    assert "⚡ EPIC" in first
    assert "⇄ gpu-box" in first
    assert "feed stale" in second


def test_agent_row_falls_back_to_quiet_context(tmp_path: Path) -> None:
    del tmp_path
    agent = make_agent(agent_name="solo")
    _first, second = _rows(build_agent_compact_lines(agent=agent))
    assert "START" in second or "WAIT" in second


def test_family_rows_summarize_shells_and_fold(tmp_path: Path) -> None:
    root, _child = make_agent_session(tmp_path)
    compact = build_agent_compact_lines(
        agent=root,
        fold_level=FoldLevel.COLLAPSED,
        fold_scale=AGENT_SESSION_FOLD_SCALE,
    )
    first, second = _rows(compact)
    assert "shells" in first
    assert "▸" in second


def test_proc_shell_rows_show_project_and_cwd() -> None:
    agent = make_agent(
        agent_type=AgentType.PROC_SHELL,
        agent_name="shell-1",
        cl_name="demo",
        monitor_cwd="/tmp/work/checkout",
    )
    first, second = _rows(build_agent_compact_lines(agent=agent))
    assert "shell-1" in first
    assert "demo" in first
    assert "checkout" in second


def test_unassigned_name_is_dim() -> None:
    agent = make_agent(agent_name=None)
    first, _second = _rows(build_agent_compact_lines(agent=agent))
    assert "unassigned" in first


def test_step_rows_use_fallback_kind_name() -> None:
    agent = make_agent(
        agent_type=AgentType.WORKFLOW,
        parent_workflow="demo",
        step_name="setup",
        step_type="bash",
    )
    first, _second = _rows(build_agent_compact_lines(agent=agent))
    assert first.strip()


def test_tribe_rows_carry_label_status_and_fold() -> None:
    snapshot = make_tribe_snapshot()
    compact = build_tribe_compact_lines(
        snapshot=snapshot, fold_level=FoldLevel.COLLAPSED
    )
    first, second = _rows(compact)
    assert snapshot.label in first
    assert snapshot.status in first
    assert "lane" in second
    assert snapshot.runtime_span in second
    assert "▸" in second


def test_workflow_rows_carry_name_model_and_status() -> None:
    agent = make_agent(
        agent_type=AgentType.WORKFLOW,
        workflow="demo",
        model="codex/gpt-5",
        llm_provider="codex",
        status="RUNNING",
        activity="building",
        start_time=datetime(2024, 1, 1, 14, 23, 45),
    )
    first, second = _rows(build_workflow_compact_lines(agent=agent))
    assert "demo" in first
    assert "CODEX" in first
    assert "RUNNING" in second
    assert "building" in second


def _clan_compact_args(container: object, *, now: datetime | None = None) -> dict:
    from sase.ace.tui.models.agent import Agent

    assert isinstance(container, Agent)
    members = ordered_clan_members(container)
    family_members = tuple(m for m in members if family_children(m))
    agent_count = sum(
        max(1, len(family_rows(m, family_children(m)))) if family_children(m) else 1
        for m in members
    )
    return {
        "agent": container,
        "counts": clan_member_counts(container),
        "agent_count": agent_count,
        "family_count": len(family_members),
        "now": now,
    }


def test_clan_rows_carry_name_status_and_count_chip() -> None:
    first = make_clan_agent(
        "research.first",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    second = make_clan_agent(
        "research.second",
        status="FAILED",
        start=datetime(2026, 7, 17, 12, 1, 0),
        stop=datetime(2026, 7, 17, 12, 1, 45),
        model=None,
    )
    container = project_clan_tree([second, first])[0]
    container.clan_tribes = ("epic", "review")
    args = _clan_compact_args(container, now=datetime(2026, 7, 17, 12, 4, 0))
    compact = build_clan_compact_lines(
        fold_level=FoldLevel.COLLAPSED,
        **args,  # type: ignore[arg-type]
    )
    assert compact.no_wrap is True
    assert compact.overflow == "ellipsis"
    first_row, second_row = _rows(compact)
    assert "research" in first_row
    assert container.display_status in first_row
    assert "[" in first_row
    assert "@epic" in second_row
    assert "@review" in second_row
    assert "2 agents" in second_row
    assert "2m" in second_row
    assert "▸ 1/3" in second_row


def test_clan_rows_overflow_tribe_chips_after_three() -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    container = project_clan_tree([member])[0]
    container.clan_tribes = ("one", "two", "three", "four", "five")
    args = _clan_compact_args(container)
    _first, second = _rows(
        build_clan_compact_lines(
            fold_level=FoldLevel.COLLAPSED,
            **args,  # type: ignore[arg-type]
        )
    )
    assert "@one" in second
    assert "@two" in second
    assert "@three" in second
    assert "@four" not in second
    assert "+2" in second


def test_clan_rows_use_singular_and_plural_member_summary() -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    container = project_clan_tree([member])[0]
    args = _clan_compact_args(container)
    _first, second = _rows(
        build_clan_compact_lines(
            fold_level=FoldLevel.COLLAPSED,
            **args,  # type: ignore[arg-type]
        )
    )
    assert "1 agent" in second
    assert "2 agents" not in second

    from sase.ace.tui.models._agent_clan import ClanStatusCounts

    plural = build_clan_compact_lines(
        agent=container,
        counts=ClanStatusCounts(),
        agent_count=2,
        family_count=1,
        fold_level=FoldLevel.COLLAPSED,
    )
    _first_plural, second_plural = _rows(plural)
    assert "2 agents" in second_plural
    assert "1 family" in second_plural

    plural_families = build_clan_compact_lines(
        agent=container,
        counts=ClanStatusCounts(),
        agent_count=3,
        family_count=2,
        fold_level=FoldLevel.COLLAPSED,
    )
    assert "2 families" in _rows(plural_families)[1]


def test_clan_rows_carry_fold_chip_at_each_level() -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    container = project_clan_tree([member])[0]
    args = _clan_compact_args(container)
    assert (
        "▸ 1/3"
        in _rows(
            build_clan_compact_lines(
                fold_level=FoldLevel.COLLAPSED,
                **args,  # type: ignore[arg-type]
            )
        )[1]
    )
    assert (
        "▾ 2/3"
        in _rows(
            build_clan_compact_lines(
                fold_level=FoldLevel.EXPANDED,
                **args,  # type: ignore[arg-type]
            )
        )[1]
    )
    assert (
        "▼ 3/3"
        in _rows(
            build_clan_compact_lines(
                fold_level=FoldLevel.FULLY_EXPANDED,
                **args,  # type: ignore[arg-type]
            )
        )[1]
    )
    assert CLAN_FOLD_SCALE == (
        FoldLevel.COLLAPSED,
        FoldLevel.EXPANDED,
        FoldLevel.FULLY_EXPANDED,
    )


def test_clan_rows_without_tribes() -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    container = project_clan_tree([member])[0]
    assert not container.clan_tribes
    args = _clan_compact_args(container)
    first, second = _rows(
        build_clan_compact_lines(
            fold_level=FoldLevel.COLLAPSED,
            **args,  # type: ignore[arg-type]
        )
    )
    assert "research" in first
    assert "@" not in second
    assert "1 agent" in second
