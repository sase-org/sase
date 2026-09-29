"""Handoff-reconcile coverage for gate-shell reclaim sweeps.

Covers snapshot reuse/refresh, deadline and time-budget deferral, the shared
caller-provided snapshot, and cursor persistence. Error-contract coverage
lives in ``test_reclaim_errors.py`` and single-gate dispositions in
``test_reclaim_dispositions.py``. The original ``test_reclaim.py`` module
remains as a facade that lazily re-exports every test here under its historic
import path.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import sase.gate_turn.handoff as handoff_mod
import sase.gate_turn.reclaim as reclaim_mod
import sase.gate_turn.store as store_mod
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.paths import sase_projects_dir
from sase.gate_turn.handoff import load_reconcile_cursor
from sase.gate_turn.reclaim import (
    reclaim_pending_gate_turns,
    reconcile_incomplete_gate_handoffs,
)
from sase.gate_turn.store import GateTurnSnapshot
from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX, agent_session_value
from tests.gate_turn._cli_fixtures import (
    make_gate_turn,
    patch_gate_turn_project_records,
)
from tests.gate_turn._reclaim_helpers import RECLAIM_PROJECT
from tests.monitor._fixtures import record_from_disk


class _Killed(BaseException):
    """Stands in for the SIGKILL that ends a chop mid-pass."""


def _settled_gate(
    timestamp: str, *, lane: str, changed_after_snapshot: bool = False
) -> str:
    """Create an answered gate shell whose metadata was last written an hour ago."""
    artifacts_dir = make_gate_turn(
        RECLAIM_PROJECT,
        timestamp,
        f"{lane}--gate",
        lane=lane,
        gate_id=f"gate-{timestamp}",
        gate_state="answered",
    )
    if not changed_after_snapshot:
        an_hour_ago = time.time() - 3600
        os.utime(Path(artifacts_dir) / "agent_meta.json", (an_hour_ago, an_hour_ago))
    return artifacts_dir


def _settled_gates(count: int) -> list[str]:
    return [
        _settled_gate(f"2026091200000{index}", lane=f"lane{index}")
        for index in range(count)
    ]


def _coder_successor(timestamp: str, *, lane: str) -> str:
    """Create the coder agent that a gate's handoff launched into ``lane``."""
    artifacts_dir = (
        sase_projects_dir()
        / RECLAIM_PROJECT
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    artifacts_dir.mkdir(parents=True)
    meta = {"agent_session": lane, "name": f"{lane}{PLAN_CHAIN_CODER_SUFFIX}"}
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return str(artifacts_dir)


def _serve_index(
    monkeypatch: pytest.MonkeyPatch, artifacts_dirs: list[str]
) -> list[str | None]:
    """Serve *artifacts_dirs* as the artifact index, recording each full read."""
    patch_gate_turn_project_records(monkeypatch, artifacts_dirs)
    serve = store_mod.project_records
    reads: list[str | None] = []

    def read(project_name: str | None) -> list[AgentArtifactRecordWire]:
        reads.append(project_name)
        return serve(project_name)

    monkeypatch.setattr(store_mod, "project_records", read)
    return reads


def _serve_agent_session_query(
    monkeypatch: pytest.MonkeyPatch, artifacts_dirs: tuple[str, ...] = ()
) -> list[tuple[str | None, str]]:
    """Replace the per-agent-session index query, recording each call."""
    queries: list[tuple[str | None, str]] = []

    def query(
        project_name: str | None, agent_session: str
    ) -> list[AgentArtifactRecordWire]:
        queries.append((project_name, agent_session))
        return [record_from_disk(artifacts_dir) for artifacts_dir in artifacts_dirs]

    monkeypatch.setattr(handoff_mod, "_agent_session_records", query)
    return queries


def _serve_index_with_taken_at(
    monkeypatch: pytest.MonkeyPatch,
    dirs_by_read: list[list[str]],
    *,
    taken_ats: list[float],
) -> list[str | None]:
    """Stub the shared snapshot read with an explicit, non-wall-clock ``taken_at``.

    A gate whose metadata changed "after the snapshot" needs a snapshot whose
    ``taken_at`` reliably predates it by more than the mtime slack, which
    real elapsed time during a fast test cannot guarantee.
    """
    reads: list[str | None] = []

    def fake(*, project: str | None = None) -> GateTurnSnapshot:
        index = len(reads)
        reads.append(project)
        dirs = dirs_by_read[min(index, len(dirs_by_read) - 1)]
        records = [record_from_disk(d) for d in dirs]
        members: dict[tuple[str, str], list[AgentArtifactRecordWire]] = {}
        for record in records:
            meta = record.agent_meta
            if meta is not None and meta.agent_session:
                key = (record.project_name, meta.agent_session)
                members.setdefault(key, []).append(record)
        return GateTurnSnapshot(
            taken_at=taken_ats[min(index, len(taken_ats) - 1)],
            gate_turns=tuple(store_mod._gate_turns_from_records(records)),
            agent_session_members={key: tuple(value) for key, value in members.items()},
            record_count=len(records),
        )

    monkeypatch.setattr(reclaim_mod, "load_gate_turn_snapshot", fake)
    return reads


def _stub_decisions(
    monkeypatch: pytest.MonkeyPatch,
    *,
    on_classify: Callable[[], None] = lambda: None,
) -> dict[str, dict[str, Any]]:
    """Stub the core decision and its persistence, capturing evidence by lane."""
    evidence: dict[str, dict[str, Any]] = {}

    def classify(
        meta: dict[str, Any],
        *,
        successor_evidence: dict[str, Any],
        **_kwargs: object,
    ) -> dict[str, Any]:
        on_classify()
        evidence[str(agent_session_value(meta))] = dict(successor_evidence)
        return {}

    monkeypatch.setattr(reclaim_mod, "classify_gate_handoff", classify)
    monkeypatch.setattr(reclaim_mod, "apply_decision", lambda *_args: None)
    return evidence


def test_reconcile_reads_the_artifact_index_once_for_every_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gates = _settled_gates(3)
    successor = _coder_successor("20260912000009", lane="lane1")
    index_reads = _serve_index(monkeypatch, [*gates, successor])
    agent_session_queries = _serve_agent_session_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs()

    assert summary.scanned == 3
    assert index_reads == [None]
    assert agent_session_queries == []
    assert evidence["lane1"]["attached_agent"] == f"lane1{PLAN_CHAIN_CODER_SUFFIX}"
    assert evidence["lane0"]["attached_agent"] is None


def test_reconcile_refreshes_the_snapshot_once_for_a_gate_changed_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _settled_gate("20260912000001", lane="lane", changed_after_snapshot=True)
    os.utime(Path(gate) / "agent_meta.json", (1_005.0, 1_005.0))
    successor = _coder_successor("20260912000002", lane="lane")
    index_reads = _serve_index_with_taken_at(
        monkeypatch, [[gate], [gate, successor]], taken_ats=[1_000.0, 1_010.0]
    )
    agent_session_queries = _serve_agent_session_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs()

    assert summary.scanned == 1
    assert index_reads == [None, None]
    assert agent_session_queries == []
    assert evidence["lane"]["attached_agent"] == f"lane{PLAN_CHAIN_CODER_SUFFIX}"


def test_reconcile_refreshes_the_snapshot_at_most_once_for_two_changed_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first changed gate triggers the refresh; the second just reuses it."""
    gate_a = _settled_gate("20260912000001", lane="lane-a", changed_after_snapshot=True)
    gate_b = _settled_gate("20260912000002", lane="lane-b", changed_after_snapshot=True)
    for gate in (gate_a, gate_b):
        os.utime(Path(gate) / "agent_meta.json", (1_005.0, 1_005.0))
    successor = _coder_successor("20260912000003", lane="lane-a")
    reads = _serve_index_with_taken_at(
        monkeypatch,
        [[gate_a, gate_b], [gate_a, gate_b, successor]],
        taken_ats=[1_000.0, 1_010.0],
    )
    agent_session_queries = _serve_agent_session_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs()

    assert summary.scanned == 2
    assert reads == [None, None]
    assert agent_session_queries == []
    assert evidence["lane-a"]["attached_agent"] == f"lane-a{PLAN_CHAIN_CODER_SUFFIX}"
    assert evidence["lane-b"]["attached_agent"] is None


def test_reconcile_defers_a_gate_still_changed_after_its_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _settled_gate("20260912000001", lane="lane", changed_after_snapshot=True)
    os.utime(Path(gate) / "agent_meta.json", (1_000_010.0, 1_000_010.0))
    _serve_index_with_taken_at(
        monkeypatch,
        [[gate]],
        taken_ats=[1_000_000.0, 1_000_000.0, 2_000_000.0],
    )
    agent_session_queries = _serve_agent_session_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    first = reconcile_incomplete_gate_handoffs()

    assert first.scanned == 0
    assert first.deferred == 1
    assert agent_session_queries == []
    assert evidence == {}
    assert load_reconcile_cursor(RECLAIM_PROJECT) == {}

    second = reconcile_incomplete_gate_handoffs()

    assert second.scanned == 1
    assert second.deferred == 0


def test_reconcile_skips_a_refresh_when_it_would_not_fit_before_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _settled_gate("20260912000001", lane="lane", changed_after_snapshot=True)
    _serve_index(monkeypatch, [gate])
    agent_session_queries = _serve_agent_session_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs(
        deadline=100.0, clock=lambda: 50.0, snapshot_read_seconds=60.0
    )

    assert summary.scanned == 0
    assert summary.deferred == 1
    assert agent_session_queries == []
    assert evidence == {}


def test_reconcile_defers_everything_when_its_deadline_has_already_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_index(monkeypatch, _settled_gates(3))
    _serve_agent_session_query(monkeypatch)
    _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs(deadline=0.0, clock=lambda: 1.0)

    assert summary.scanned == 0
    assert summary.deferred == 3


def test_reclaim_and_reconcile_share_one_caller_provided_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = make_gate_turn(
        RECLAIM_PROJECT,
        "20260912000000",
        "lane--gate",
        lane="lane",
        gate_id="gate-pending",
        gate_state="pending",
    )
    settled = _settled_gate("20260912000001", lane="lane2")
    index_reads = _serve_index(monkeypatch, [pending, settled])
    agent_session_queries = _serve_agent_session_query(monkeypatch)
    _stub_decisions(monkeypatch)

    snapshot = store_mod.load_gate_turn_snapshot()
    reclaim_summary = reclaim_pending_gate_turns(snapshot=snapshot)
    reconcile_summary = reconcile_incomplete_gate_handoffs(snapshot=snapshot)

    assert index_reads == [None]
    # Settling the bundle-less pending gate as "lost" makes its own unrelated
    # follow-up-evidence query through handoff_launch.launch_or_record_followup,
    # outside the reconcile pass this test exercises.
    assert agent_session_queries == [(RECLAIM_PROJECT, "lane")]
    assert reclaim_summary.scanned == 1
    assert reclaim_summary.lost == 1
    assert reconcile_summary.scanned == 1


def test_reconcile_saves_its_cursor_after_each_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gates = _settled_gates(3)
    _serve_index(monkeypatch, gates)
    _serve_agent_session_query(monkeypatch)
    classified: list[None] = []

    def killed_on_third_gate() -> None:
        if len(classified) == 2:
            raise _Killed
        classified.append(None)

    _stub_decisions(monkeypatch, on_classify=killed_on_third_gate)

    with pytest.raises(_Killed):
        reconcile_incomplete_gate_handoffs()

    assert load_reconcile_cursor(RECLAIM_PROJECT) == {
        "timestamp": "20260912000001",
        "artifacts_dir": str(Path(gates[1]).resolve()),
    }


def test_reconcile_defers_gates_past_its_time_budget_then_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_index(monkeypatch, _settled_gates(3))
    _serve_agent_session_query(monkeypatch)
    now = [0.0]

    def forty_seconds_per_gate() -> None:
        now[0] += 40.0

    _stub_decisions(monkeypatch, on_classify=forty_seconds_per_gate)

    first = reconcile_incomplete_gate_handoffs(
        time_budget_seconds=60.0, clock=lambda: now[0]
    )
    now[0] = 0.0
    second = reconcile_incomplete_gate_handoffs(
        time_budget_seconds=60.0, clock=lambda: now[0]
    )

    assert (first.scanned, first.deferred) == (2, 1)
    assert first.to_dict()["handoff_deferred"] == 1
    assert (second.scanned, second.deferred) == (1, 0)
