"""Tests for the cached Agents-tab stranded-work projection."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.bead import stranded as stranded_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models import agent_stranded
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict


@pytest.fixture(autouse=True)
def _clear_stranded_cache():
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _snapshot(*verdicts: StrandedWorkVerdict) -> StrandedReport:
    report = StrandedWorkReport(
        verdicts=verdicts,
        stranded_ids=tuple(
            verdict.bead_id for verdict in verdicts if verdict.state == "stranded"
        ),
        blocked_ids=tuple(
            verdict.bead_id for verdict in verdicts if verdict.state == "blocked"
        ),
    )
    return StrandedReport(report=report, titles={}, generated_at=1.0)


def _verdict(bead_id: str, state: str) -> StrandedWorkVerdict:
    return StrandedWorkVerdict(
        bead_id=bead_id,
        kind="phase",
        state=state,
        blocked_by=("sase-demo.1",) if state == "blocked" else (),
    )


def test_warm_reports_reuse_ttl_and_invalidate_on_store_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprints = ["store-1"]
    snapshots = iter(
        (
            _snapshot(_verdict("sase-demo.1", "stranded")),
            _snapshot(_verdict("sase-demo.1", "blocked")),
        )
    )
    loads: list[str] = []

    monkeypatch.setattr(
        agent_stranded, "_project_fingerprint", lambda _project: fingerprints[0]
    )

    def load(project_key: str) -> StrandedReport:
        loads.append(project_key)
        return next(snapshots)

    monkeypatch.setattr(stranded_module, "load_stranded_report", load)

    first = agent_stranded.warm_stranded_work_reports(("demo",))
    cached = agent_stranded.warm_stranded_work_reports(("demo",))
    fingerprints[0] = "store-2"
    refreshed = agent_stranded.warm_stranded_work_reports(("demo",))

    assert first == {"demo": frozenset({"sase-demo.1"})}
    assert cached == {}
    assert refreshed == {"demo": frozenset({"sase-demo.1"})}
    assert loads == ["demo", "demo"]


def test_agent_view_resolves_phase_task_and_waiter_states() -> None:
    phase = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-phase",
        project_file="/tmp/demo/demo.sase",
        status="DONE",
        start_time=datetime(2026, 10, 1, 12, 0),
        raw_suffix="phase",
        agent_name="sase-demo.1",
        phase_bead_id="sase-demo.1",
    )
    waiter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-waiter",
        project_file="/tmp/demo/demo.sase",
        status="WAITING",
        start_time=datetime(2026, 10, 1, 12, 1),
        raw_suffix="waiter",
        agent_name="sase-demo.land",
        waiting_for_beads=["sase-demo.1"],
    )
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        _snapshot(
            _verdict("sase-demo.1", "stranded"),
            _verdict("sase-demo", "blocked"),
        ),
        "store",
    )

    assert agent_stranded._agent_bead_id_for_stranded(phase) == "sase-demo.1"
    assert agent_stranded._stranded_verdict_for_agent(phase).state == "stranded"  # type: ignore[union-attr]
    assert agent_stranded.agent_stranded_view(waiter).waiting_on == (
        ("sase-demo.1", "stranded"),
    )
    assert agent_stranded.stranded_count_for_agents((phase, waiter)) == 1
