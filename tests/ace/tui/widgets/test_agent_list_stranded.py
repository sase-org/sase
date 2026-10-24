"""Stranded-work overlays on Agents-tab rows."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest

from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._agent_clan_waves import (
    ClanWaveSummary,
    _ClanWaveState,
    _ClanWaveView,
)
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.bead.stranded import StrandedReport
from sase.bead.stranded_presentation import (
    STRANDED_BREADCRUMB_STYLE,
    STRANDED_LEAF_STYLE,
)
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
    waiting_for: list[str] | None = None,
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
        waiting_for=waiting_for or [],
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


def _verdict(bead_id: str, state: str, **fields: object) -> StrandedWorkVerdict:
    payload: dict[str, object] = {
        "bead_id": bead_id,
        "kind": "phase",
        "state": state,
        "blocked_by": ("sase-demo.1",) if state == "blocked" else (),
    }
    payload.update(fields)
    return StrandedWorkVerdict(**payload)  # type: ignore[arg-type]


def _left(agent: Agent):
    return format_agent_option(agent, 0, is_selected=False)[0]


def _style_at(text, glyph: str) -> str:
    index = text.plain.index(glyph)
    return next(
        str(span.style) for span in text.spans if span.start <= index < span.end
    )


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

    assert "WAITING ⚐ sase-demo.1" in waiter_text.plain
    assert waiter_text.plain.count("⚐") == 1
    assert _style_at(waiter_text, "⚐") == STRANDED_LEAF_STYLE
    assert _style_at(blocked_text, "⚐") == STRANDED_BREADCRUMB_STYLE


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


def test_ancestor_clan_shows_breadcrumb_count_without_loaded_leaf() -> None:
    container = _agent(
        "sase-demo",
        status="DONE",
        raw_suffix="clan",
        is_clan_container=True,
        agent_clan="sase-demo",
        generation="g1",
    )
    _set_report(
        _verdict(
            "sase-nested.1",
            "stranded",
            parent_id="sase-nested",
            blocked_by=(),
        ),
        _verdict(
            "sase-demo",
            "blocked",
            kind="epic",
            blocked_by=("sase-nested.1",),
        ),
    )

    rendered = _left(container)

    assert "⚐1" in rendered.plain
    assert _style_at(rendered, "⚐") == STRANDED_BREADCRUMB_STYLE


def test_direct_phase_clan_count_uses_leaf_style() -> None:
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
    _set_report(
        _verdict("sase-demo.1", "stranded", parent_id="sase-demo", blocked_by=()),
    )

    rendered = _left(container)

    assert "⚐1" in rendered.plain
    assert _style_at(rendered, "⚐") == STRANDED_LEAF_STYLE


def test_blocked_member_folds_wave_pip_to_needs_you() -> None:
    blocked = _agent(
        "sase-demo.2",
        status="WAITING",
        raw_suffix="blocked",
        phase_bead_id="sase-demo.2",
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
    container.runtime_children = [blocked]
    container.clan_waves = ClanWaveSummary(
        layered=True,
        numbered_wave_count=1,
        has_seal=False,
        waves=(
            _ClanWaveView(
                number=1,
                kind="number",
                member_identities=(
                    f"{blocked.agent_type.value}:{blocked.cl_name}:"
                    f"{blocked.raw_suffix}:{blocked.agent_name}",
                ),
                ghost_names=(),
                state=_ClanWaveState.DONE,
                predecessor_identities=(),
            ),
        ),
        members=(),
        unresolved_identities=(),
    )
    _set_report(_verdict("sase-demo.2", "blocked"))

    assert "▲" in _left(container).plain


def test_agent_session_wait_falls_back_to_breadcrumb_flag() -> None:
    waiter = _agent(
        "sase-demo.land",
        status="WAITING",
        raw_suffix="waiter",
        waiting_for=["sase-demo.1"],
    )
    _set_report(_verdict("sase-demo.1", "stranded", blocked_by=()))

    rendered = _left(waiter)

    assert "WAITING ⚐)" in rendered.plain
    assert _style_at(rendered, "⚐") == STRANDED_BREADCRUMB_STYLE


def test_waiting_row_without_verdicts_is_unchanged() -> None:
    waiter = _agent(
        "sase-demo.land",
        status="WAITING",
        raw_suffix="waiter",
        waiting_for_beads=["sase-demo.1"],
        waiting_for=["sase-demo.1"],
    )

    assert "⚐" not in _left(waiter).plain
