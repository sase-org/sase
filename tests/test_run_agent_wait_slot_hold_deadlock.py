"""Tests for the hold-deadlock detection predicate at runner-slot admission."""

from __future__ import annotations

import pytest

from sase.axe.run_agent_wait_slot_candidate import hold_deadlock_armer_record
from sase.core.agent_hold_facade import arm_agent_hold, _hold_selectors_wire
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    RunningMarkerWire,
    WaitingMarkerWire,
)
from sase.xprompt.hold_directive import HoldFields, hold_fields_to_selectors

pytest.importorskip("sase_core_rs")


def _record(
    artifact_dir: str,
    *,
    agent_name: str,
    running: bool = False,
    has_done_marker: bool = False,
    waiting_for: list[str] | None = None,
    wait_for_hoods: list[str] | None = None,
    family: str | None = None,
    clan: str | None = None,
    workflow: str | None = None,
    tribe: str | None = None,
    wait_for: list[str] | None = None,
) -> AgentArtifactRecordWire:
    waiting = None
    if waiting_for is not None or wait_for_hoods is not None:
        waiting = WaitingMarkerWire(
            waiting_for=waiting_for or [],
            wait_for_hoods=wait_for_hoods or [],
        )
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/proj",
        project_file="/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp=artifact_dir.rsplit("/", 1)[-1],
        agent_meta=AgentMetaWire(
            name=agent_name,
            agent_family=family,
            agent_clan=clan,
            workflow_name=workflow,
            tribe=tribe,
            wait_for=wait_for or [],
            wait_for_hoods=wait_for_hoods or [],
        ),
        running=RunningMarkerWire(pid=1) if running else None,
        waiting=waiting,
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


def _deadlock(
    *,
    armer_dir: str,
    candidate_name: str,
    records: list[AgentArtifactRecordWire],
    candidate: dict[str, object] | None = None,
) -> AgentArtifactRecordWire | None:
    return hold_deadlock_armer_record(
        held_by="agent:armer.agent",
        candidate_agent_name=candidate_name,
        active_holds=[_hold("agent:armer.agent", armer_dir)],
        records=records,
        candidate=candidate,
    )


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

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="candidate.agent",
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

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="candidate.agent",
        records=records,
    )

    assert result is armer_record


def test_branched_cycle_visits_the_second_wait_branch() -> None:
    """An armer waiting on [safe, bridge] must still see the bridge cycle.

    The previous single-path ``next(...)`` walk took only the first name and
    missed the deadlock when that branch was harmless.
    """
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    armer_record = _record(
        armer_dir,
        agent_name="armer.agent",
        waiting_for=["safe.agent", "bridge.agent"],
    )
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        armer_record,
        _record(
            "/proj/artifacts/ace-run/20260910120002",
            agent_name="safe.agent",
            waiting_for=["unrelated.agent"],
        ),
        _record(
            "/proj/artifacts/ace-run/20260910120003",
            agent_name="bridge.agent",
            waiting_for=["candidate.agent"],
        ),
    ]

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="candidate.agent",
        records=records,
    )

    assert result is armer_record


def test_longer_cycle_with_repeated_vertices_still_reaches() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    armer_record = _record(armer_dir, agent_name="armer.agent", waiting_for=["loop.a"])
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        armer_record,
        _record(
            "/proj/artifacts/ace-run/20260910120002",
            agent_name="loop.a",
            waiting_for=["loop.b"],
        ),
        _record(
            "/proj/artifacts/ace-run/20260910120003",
            agent_name="loop.b",
            waiting_for=["loop.a", "candidate.agent"],
        ),
    ]

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="candidate.agent",
        records=records,
    )

    assert result is armer_record


def test_hood_mediated_cycle_uses_wait_for_hoods() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    armer_record = _record(
        armer_dir,
        agent_name="armer.agent",
        waiting_for=["safe.agent"],
        wait_for_hoods=["research"],
    )
    records = [
        _record(
            "/proj/artifacts/ace-run/20260910120000",
            agent_name="research.worker--code",
            family="research.worker",
        ),
        armer_record,
        _record(
            "/proj/artifacts/ace-run/20260910120002",
            agent_name="safe.agent",
            waiting_for=["unrelated.agent"],
        ),
    ]

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="research.worker--code",
        records=records,
        candidate={
            "artifact_dir": "/proj/artifacts/ace-run/20260910120000",
            "agent_name": "research.worker--code",
            "family": "research.worker",
            "timestamp": "20260910120000",
        },
    )

    assert result is armer_record


def test_no_deadlock_when_armer_is_running() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        _record(armer_dir, agent_name="armer.agent", running=True),
    ]

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="candidate.agent",
        records=records,
    )

    assert result is None


def test_no_deadlock_when_armer_is_not_waiting_on_the_candidate() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        _record(armer_dir, agent_name="armer.agent", waiting_for=["someone.else"]),
    ]

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="candidate.agent",
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

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="candidate.agent",
        records=records,
    )

    assert result is None


def test_settled_branch_is_not_a_mutual_block() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    records = [
        _record("/proj/artifacts/ace-run/20260910120000", agent_name="candidate.agent"),
        _record(armer_dir, agent_name="armer.agent", waiting_for=["done.agent"]),
        _record(
            "/proj/artifacts/ace-run/20260910120002",
            agent_name="done.agent",
            waiting_for=["candidate.agent"],
            has_done_marker=True,
        ),
    ]

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="candidate.agent",
        records=records,
    )

    assert result is None


def test_family_wait_name_matches_role_suffixed_candidate() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    armer_record = _record(armer_dir, agent_name="armer.agent", waiting_for=["team"])
    records = [
        _record(
            "/proj/artifacts/ace-run/20260910120000",
            agent_name="team--code",
            family="team",
        ),
        armer_record,
    ]

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="team--code",
        records=records,
        candidate={
            "agent_name": "team--code",
            "family": "team",
            "timestamp": "20260910120000",
        },
    )

    assert result is armer_record


def test_cli_and_directive_holds_exercise_family_identity() -> None:
    cli_selectors = _hold_selectors_wire(names=["team"])
    directive_selectors = hold_fields_to_selectors(HoldFields(names=("team",)))
    assert cli_selectors["families"] == ["team"]
    assert directive_selectors["families"] == ["team"]

    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    armer_record = _record(armer_dir, agent_name="armer.agent", waiting_for=["team"])
    records = [
        _record(
            "/proj/artifacts/ace-run/20260910120000",
            agent_name="team--code",
            family="team",
        ),
        armer_record,
    ]
    cli_hold = arm_agent_hold(
        armer={
            "kind": "agent",
            "key": "agent:armer.agent",
            "display": "armer.agent",
            "project": "proj",
            "agent_name": "armer.agent",
            "pid": 4242,
            "done_marker_path": f"{armer_dir}/done.json",
        },
        names=["team"],
        scope="host",
        ttl_seconds=60,
        now=1_000.0,
    ).record
    directive_hold = arm_agent_hold(
        armer={
            "kind": "agent",
            "key": "agent:armer.agent",
            "display": "armer.agent",
            "project": "proj",
            "agent_name": "armer.agent",
            "pid": 4242,
            "done_marker_path": f"{armer_dir}/done.json",
        },
        selectors=directive_selectors,
        scope="host",
        ttl_seconds=60,
        now=1_000.0,
    ).record

    cli_result = hold_deadlock_armer_record(
        held_by="agent:armer.agent",
        candidate_agent_name="team--code",
        active_holds=[cli_hold],
        records=records,
        candidate={"agent_name": "team--code", "family": "team"},
    )
    directive_result = hold_deadlock_armer_record(
        held_by="agent:armer.agent",
        candidate_agent_name="team--code",
        active_holds=[directive_hold],
        records=records,
        candidate={"agent_name": "team--code", "family": "team"},
    )

    assert cli_result is armer_record
    assert directive_result is armer_record
    assert cli_hold["selectors"]["families"] == ["team"]
    assert directive_hold["selectors"]["families"] == ["team"]


def test_hood_cutoff_ignores_members_launched_after_the_waiter() -> None:
    armer_dir = "/proj/artifacts/ace-run/20260910120001"
    records = [
        _record(
            "/proj/artifacts/ace-run/20260910120002",
            agent_name="research.worker--code",
            family="research.worker",
        ),
        _record(
            armer_dir,
            agent_name="armer.agent",
            wait_for_hoods=["research"],
            waiting_for=[],
        ),
    ]

    result = _deadlock(
        armer_dir=armer_dir,
        candidate_name="research.worker--code",
        records=records,
        candidate={
            "artifact_dir": "/proj/artifacts/ace-run/20260910120002",
            "agent_name": "research.worker--code",
            "family": "research.worker",
            "timestamp": "20260910120002",
        },
    )

    assert result is None
