"""Detail surfaces for stranded and blocked bead work."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents import _stranded_toasts
from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_wait_section import (
    ResponsiveWaitSection,
    build_wait_lanes,
)
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _verdict(bead_id: str, state: str, **fields: object) -> StrandedWorkVerdict:
    return StrandedWorkVerdict(
        bead_id=bead_id,
        kind="phase",
        state=state,
        reason="kept" if state == "stranded" else None,
        since=1.0,
        blocked_by=("sase-demo.1",) if state == "blocked" else (),
        **fields,
    )


def _set_report(*verdicts: StrandedWorkVerdict) -> None:
    report = StrandedWorkReport(
        verdicts=verdicts,
        stranded_ids=tuple(v.bead_id for v in verdicts if v.state == "stranded"),
        blocked_ids=tuple(v.bead_id for v in verdicts if v.state == "blocked"),
    )
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo", StrandedReport(report=report, titles={}, generated_at=3601.0), "test"
    )


def test_bead_wait_lane_replaces_status_with_stranded_age() -> None:
    agent = make_agent(
        agent_name="sase-demo.land",
        project_file="/tmp/demo/demo.sase",
        status="WAITING",
        waiting_for_beads=["sase-demo.1"],
    )
    _set_report(_verdict("sase-demo.1", "stranded"))

    lanes = build_wait_lanes(
        agent,
        agent_status_buckets={},
        clan_wait_member_statuses=None,
        tribe_wait_bindings=None,
        wait_bead_statuses=(("sase-demo.1", "in_progress"),),
    )
    rendered = ResponsiveWaitSection(lanes).logical_text.plain

    assert "[beads] sase-demo.1 ⚐ stranded 1h" in rendered
    assert "◐" not in rendered


def test_stranded_transition_toast_uses_quiet_first_baseline() -> None:
    _stranded_toasts._SEEN_LEAVES.clear()
    _set_report()
    notices: list[str] = []
    assert (
        _stranded_toasts.announce_stranded_transitions(notices.append, ("demo",)) == []
    )

    _set_report(_verdict("sase-demo.1", "stranded", last_turn="sase-demo.1--3"))
    messages = _stranded_toasts.announce_stranded_transitions(notices.append, ("demo",))

    assert messages == [
        "⚐ sase-demo.1 is stranded: --3 ended with bead_action keep; nothing resumes it."
    ]
    assert notices == messages


def test_live_query_stranded_field_is_true_for_owner_row() -> None:
    from sase.ace.tui.models.agent_live_query import agent_live_query_entry

    owner = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/tmp/demo/demo.sase",
        status="DONE",
        start_time=datetime(2026, 10, 1, 12, 0),
        agent_name="sase-demo.1",
        phase_bead_id="sase-demo.1",
    )
    _set_report(_verdict("sase-demo.1", "stranded"))

    assert agent_live_query_entry(owner)["fields"]["stranded"] == (True,)
