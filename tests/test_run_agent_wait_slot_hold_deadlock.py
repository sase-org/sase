"""Tests for the hold-deadlock detection predicate at runner-slot admission."""

from __future__ import annotations

from sase.axe.run_agent_wait_slot_candidate import hold_deadlock_armer_record
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    RunningMarkerWire,
    WaitingMarkerWire,
)


def _record(
    artifact_dir: str,
    *,
    agent_name: str,
    running: bool = False,
    has_done_marker: bool = False,
    waiting_for: list[str] | None = None,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/proj",
        project_file="/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp=artifact_dir.rsplit("/", 1)[-1],
        agent_meta=AgentMetaWire(name=agent_name),
        running=RunningMarkerWire(pid=1) if running else None,
        waiting=(
            None if waiting_for is None else WaitingMarkerWire(waiting_for=waiting_for)
        ),
        has_done_marker=has_done_marker,
    )


def _hold(armer_key: str, armer_dir: str) -> dict[str, object]:
    return {
        "armer": {
            "kind": "agent",
            "key": armer_key,
            "done_marker_path": f"{armer_dir}/done.json",
        }
    }


def test_direct_deadlock_returns_the_armer_record() -> None:
    candidate_dir = "/proj/artifacts/ace-run/20260910120000"
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    armer_record = _record(
        armer_dir, agent_name="armer.agent", waiting_for=["candidate.agent"]
    )
    records = [
        _record(candidate_dir, agent_name="candidate.agent"),
        armer_record,
    ]

    result = hold_deadlock_armer_record(
        held_by="agent:armer.agent",
        candidate_agent_name="candidate.agent",
        active_holds=[_hold("agent:armer.agent", armer_dir)],
        records=records,
    )

    assert result is armer_record


def test_transitive_deadlock_walks_the_armers_own_wait_set() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    middle_dir = "/proj/artifacts/ace-run/20260910120002"
    armer_record = _record(
        armer_dir, agent_name="armer.agent", waiting_for=["middle.agent"]
    )
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        armer_record,
        _record(middle_dir, agent_name="middle.agent", waiting_for=["candidate.agent"]),
    ]

    result = hold_deadlock_armer_record(
        held_by="agent:armer.agent",
        candidate_agent_name="candidate.agent",
        active_holds=[_hold("agent:armer.agent", armer_dir)],
        records=records,
    )

    assert result is armer_record


def test_no_deadlock_when_armer_is_running() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        _record(armer_dir, agent_name="armer.agent", running=True),
    ]

    result = hold_deadlock_armer_record(
        held_by="agent:armer.agent",
        candidate_agent_name="candidate.agent",
        active_holds=[_hold("agent:armer.agent", armer_dir)],
        records=records,
    )

    assert result is None


def test_no_deadlock_when_armer_is_not_waiting_on_the_candidate() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        _record(armer_dir, agent_name="armer.agent", waiting_for=["someone.else"]),
    ]

    result = hold_deadlock_armer_record(
        held_by="agent:armer.agent",
        candidate_agent_name="candidate.agent",
        active_holds=[_hold("agent:armer.agent", armer_dir)],
        records=records,
    )

    assert result is None


def test_no_deadlock_for_non_agent_armer_kinds() -> None:
    result = hold_deadlock_armer_record(
        held_by="cli:host:123",
        candidate_agent_name="candidate.agent",
        active_holds=[{"armer": {"kind": "cli", "key": "cli:host:123"}}],
        records=[],
    )

    assert result is None


def test_no_deadlock_when_hold_is_not_found() -> None:
    result = hold_deadlock_armer_record(
        held_by="agent:missing",
        candidate_agent_name="candidate.agent",
        active_holds=[],
        records=[],
    )

    assert result is None


def test_cycle_in_wait_chain_does_not_loop_forever() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    other_dir = "/proj/artifacts/ace-run/20260910120002"
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        _record(armer_dir, agent_name="armer.agent", waiting_for=["other.agent"]),
        _record(other_dir, agent_name="other.agent", waiting_for=["armer.agent"]),
    ]

    result = hold_deadlock_armer_record(
        held_by="agent:armer.agent",
        candidate_agent_name="candidate.agent",
        active_holds=[_hold("agent:armer.agent", armer_dir)],
        records=records,
    )

    assert result is None
