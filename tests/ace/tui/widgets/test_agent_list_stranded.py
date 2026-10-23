"""Stranded-work overlays on Agents-tab rows."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest

from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.bead.stranded import StrandedReport
from sase.bead.stranded_presentation import STRANDED_BREADCRUMB_STYLE
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict


@pytest.fixture(autouse=True)
def _clear_stranded_cache() -> Iterator[None]:
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _agent(
    name: str | None,
    *,
    status: str,
    raw_suffix: str,
    phase_bead_id: str | None = None,
    waiting_for_beads: list[str] | None = None,
    is_clan_container: bool = False,
    agent_clan: str | None = None,
    generation: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name or raw_suffix,
        project_file="/tmp/demo/demo.sase",
        status=status,
        start_time=datetime(2026, 10, 1, 12, 0),
        stop_time=datetime(2026, 10, 1, 12, 1) if status == "DONE" else None,
        raw_suffix=raw_suffix,
        agent_name=name,
        phase_bead_id=phase_bead_id,
        waiting_for_beads=waiting_for_beads or [],
        is_clan_container=is_clan_container,
        agent_clan=agent_clan,
        agent_clan_generation=generation,
    )


def _set_report(*verdicts: StrandedWorkVerdict) -> None:
    report = StrandedWorkReport(
        verdicts=verdicts,
        stranded_ids=tuple(
            verdict.bead_id for verdict in verdicts if verdict.state == "stranded"
        ),
        blocked_ids=tuple(
            verdict.bead_id for verdict in verdicts if verdict.state == "blocked"
        ),
    )
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        StrandedReport(report=report, titles={}, generated_at=1.0),
        "test",
    )


def _verdict(bead_id: str, state: str) -> StrandedWorkVerdict:
    return StrandedWorkVerdict(
        bead_id=bead_id,
        kind="phase",
        state=state,
        blocked_by=("sase-demo.1",) if state == "blocked" else (),
    )


def _left(agent: Agent):
    return format_agent_option(agent, 0, is_selected=False)[0]


def test_stranded_done_row_uses_overlay_and_leaf_flag() -> None:
    leaf = _agent(
        "sase-demo.1",
        status="DONE",
        raw_suffix="leaf",
        phase_bead_id="sase-demo.1",
    )
    _set_report(_verdict("sase-demo.1", "stranded"))

    rendered = _left(leaf)

    assert "(STRANDED ⚐)" in rendered.plain


def test_waiter_gets_leaf_flag_and_blocked_ancestor_gets_dim_breadcrumb() -> None:
    waiter = _agent(
        "sase-demo.land",
        status="WAITING",
        raw_suffix="waiter",
        waiting_for_beads=["sase-demo.1"],
    )
    blocked = _agent(
        "sase-demo.2",
        status="WAITING",
        raw_suffix="blocked",
        phase_bead_id="sase-demo.2",
    )
    _set_report(
        _verdict("sase-demo.1", "stranded"),
        _verdict("sase-demo.2", "blocked"),
    )

    waiter_text = _left(waiter)
    blocked_text = _left(blocked)

    assert "WAITING sase-demo.1 ⚐" in waiter_text.plain
    flag_at = blocked_text.plain.index("⚐")
    flag_style = next(
        str(span.style)
        for span in blocked_text.spans
        if span.start <= flag_at < span.end
    )
    assert flag_style == STRANDED_BREADCRUMB_STYLE


def test_clan_row_summarizes_stranded_member_count() -> None:
    leaf = _agent(
        "sase-demo.1",
        status="DONE",
        raw_suffix="leaf",
        phase_bead_id="sase-demo.1",
        agent_clan="sase-demo",
        generation="g1",
    )
    container = _agent(
        "sase-demo",
        status="DONE",
        raw_suffix="clan",
        is_clan_container=True,
        agent_clan="sase-demo",
        generation="g1",
    )
    container.runtime_children = [leaf]
    _set_report(_verdict("sase-demo.1", "stranded"))

    assert "⚐1" in _left(container).plain
