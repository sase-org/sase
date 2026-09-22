"""Two-row compact identity lines for prompt-panel documents."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.fold_scale import FAMILY_FOLD_SCALE
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)
from sase.ace.tui.widgets.prompt_panel._identity_header_compact import (
    build_agent_compact_lines,
    build_tribe_compact_lines,
    build_workflow_compact_lines,
)
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
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
    root, _child = make_family(tmp_path)
    compact = build_agent_compact_lines(
        agent=root,
        fold_level=FoldLevel.COLLAPSED,
        fold_scale=FAMILY_FOLD_SCALE,
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
