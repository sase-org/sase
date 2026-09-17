"""Result-contract coverage for gate-shell reclaim sweeps."""

from __future__ import annotations

import dataclasses
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import sase.gate_shell.handoff as handoff_mod
import sase.gate_shell.reclaim as reclaim_mod
import sase.gate_shell.store as store_mod
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.paths import sase_projects_dir
from sase.gate_shell.handoff import load_reconcile_cursor
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.reclaim import (
    _MAX_ERROR_DETAILS,
    GateShellReclaimSummary,
    _reclaim_one,
    reclaim_pending_gate_shells,
    reconcile_incomplete_gate_handoffs,
)
from sase.gate_shell.store import GateShellSnapshot
from sase.notification_gates.decision import accept_gate_decision
from sase.notification_gates.executor import cancel_gate as real_cancel_gate
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.paths import CANCELLATION_FILENAME
from sase.notification_gates.service import create_gate
from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX
from tests._notification_gates_fixtures import gate_spec
from tests.gate_shell._cli_fixtures import (
    gate_shell_home,
    make_gate_shell,
    patch_gate_shell_project_records,
)
from tests.monitor._fixtures import record_from_disk

__all__ = ["gate_shell_home"]


def _record(
    *,
    gate_id: str,
    member_agent_name: str,
    gate_state: str = "pending",
) -> GateShellRecord:
    return GateShellRecord(
        gate_id=gate_id,
        member_agent_name=member_agent_name,
        lane="lane",
        project_name="proj",
        artifacts_dir="/tmp/artifacts",
        timestamp="20260828120000",
        kind="custom",
        gate_state=gate_state,  # type: ignore[arg-type]
        start_status="WAIT",
        stop_status="DONE",
        accent="#00D7AF",
        label="Review",
        reason="wait",
        creator_agent="lane--0",
        bundle_path="/tmp/bundle",
        notification_id="notif-1",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )


def test_reclaim_records_error_details_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = _record(gate_id="gate-bad", member_agent_name="lane--gate-bad")
    succeeding = _record(gate_id="gate-good", member_agent_name="lane--gate-good")
    monkeypatch.setattr(
        reclaim_mod,
        "list_gate_shells",
        lambda *, project=None: [failing, succeeding],
    )

    def _reclaim_one(
        record: GateShellRecord,
        *,
        now: float,
        grace_seconds: int,
    ) -> str | None:
        del now, grace_seconds
        if record.gate_id == "gate-bad":
            raise RuntimeError("bundle exploded")
        return "answered"

    monkeypatch.setattr(reclaim_mod, "_reclaim_one", _reclaim_one)

    summary = reclaim_pending_gate_shells()

    assert summary.scanned == 2
    assert summary.errors == 1
    assert summary.answered == 1
    assert len(summary.error_details) == 1
    detail = summary.error_details[0]
    assert detail.startswith("lane--gate-bad: RuntimeError: bundle exploded")


def test_reclaim_error_details_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        _record(gate_id=f"gate-{index}", member_agent_name=f"lane--gate-{index}")
        for index in range(_MAX_ERROR_DETAILS + 2)
    ]
    monkeypatch.setattr(
        reclaim_mod,
        "list_gate_shells",
        lambda *, project=None: records,
    )

    def _reclaim_one(
        record: GateShellRecord,
        *,
        now: float,
        grace_seconds: int,
    ) -> str | None:
        del now, grace_seconds
        raise RuntimeError(record.gate_id)

    monkeypatch.setattr(reclaim_mod, "_reclaim_one", _reclaim_one)

    summary = reclaim_pending_gate_shells()

    assert summary.scanned == _MAX_ERROR_DETAILS + 2
    assert summary.errors == _MAX_ERROR_DETAILS + 2
    assert len(summary.error_details) == _MAX_ERROR_DETAILS


def test_reclaim_summary_to_dict_omits_error_details() -> None:
    summary = GateShellReclaimSummary(
        scanned=2,
        answered=1,
        errors=1,
        error_details=("lane--gate: RuntimeError: boom",),
    )

    payload = summary.to_dict()

    assert payload == {
        "scanned": 2,
        "answered": 1,
        "stopped": 0,
        "timed_out": 0,
        "lost": 0,
        "accepted_unfinished": 0,
        "accepted_failed": 0,
        "accepted_owner_lost": 0,
        "errors": 1,
    }
    assert "error_details" not in payload


def _record_for_bundle(bundle_path: Path, *, gate_id: str) -> GateShellRecord:
    record = _record(gate_id=gate_id, member_agent_name=f"lane--{gate_id}")
    return dataclasses.replace(record, bundle_path=str(bundle_path))


def _settlement_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str, str | None]]:
    """Stub the (slow, real-store-backed) shell settlement, recording calls."""
    settled: list[tuple[str, str, str | None]] = []

    def fake_settle(
        record: GateShellRecord,
        *,
        gate_state: str,
        reason: str | None = None,
        **_kwargs: object,
    ) -> GateShellRecord:
        settled.append((record.gate_id, gate_state, reason))
        return record

    monkeypatch.setattr(reclaim_mod, "settle_gate_shell", fake_settle)
    return settled


def _gate_deadline(bundle_path: Path) -> float:
    envelope, _adapter = load_and_verify_bundle(bundle_path)
    return float(envelope["created_at_unix"]) + float(envelope["gate_timeout_seconds"])


def test_reclaim_defers_an_accepted_unfinished_gate_without_settling(
    gate_shell_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_gate(gate_spec(request_id="accepted-unfinished", timeout=1.0))
    accept_gate_decision(result.bundle_path, ["accept"], {})
    record = _record_for_bundle(result.bundle_path, gate_id="accepted-unfinished")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    # Well past both the review deadline and the reclaim grace window: the
    # accepted-unfinished disposition must still outrank them.
    outcome = _reclaim_one(record, now=deadline + 10_000, grace_seconds=1)

    assert outcome == "accepted_unfinished"
    assert settled == []
    assert not (result.bundle_path / CANCELLATION_FILENAME).exists()
    assert not result.response_path.exists()


def test_reclaim_settles_an_unaccepted_expired_review_gate_as_timeout(
    gate_shell_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_gate(gate_spec(request_id="unaccepted-timeout", timeout=1.0))
    record = _record_for_bundle(result.bundle_path, gate_id="unaccepted-timeout")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    outcome = _reclaim_one(record, now=deadline + 1, grace_seconds=300)

    assert outcome == "timeout"
    assert settled == [("unaccepted-timeout", "timeout", "gate timed out")]
    cancellation = json.loads(
        (result.bundle_path / CANCELLATION_FILENAME).read_text(encoding="utf-8")
    )
    assert cancellation["reason"] == "timeout"


def test_reclaim_settles_an_unaccepted_expired_grace_gate_as_lost(
    gate_shell_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = create_gate(gate_spec(request_id="unaccepted-lost", timeout=1.0))
    record = _record_for_bundle(result.bundle_path, gate_id="unaccepted-lost")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    outcome = _reclaim_one(record, now=deadline + 1000, grace_seconds=1)

    assert outcome == "lost"
    assert settled == [("unaccepted-lost", "lost", "gate deadline grace passed")]
    cancellation = json.loads(
        (result.bundle_path / CANCELLATION_FILENAME).read_text(encoding="utf-8")
    )
    assert cancellation["reason"] == "grace_expired"


def test_reclaim_expired_review_yields_to_a_racing_acceptance(
    gate_shell_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A decision accepted between reclaim's check and its locked cancel wins."""
    result = create_gate(gate_spec(request_id="race-review", timeout=1.0))
    record = _record_for_bundle(result.bundle_path, gate_id="race-review")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    def racing_cancel_gate(bundle_path: Path, **kwargs: object) -> dict[str, object]:
        accept_gate_decision(bundle_path, ["accept"], {})
        return real_cancel_gate(bundle_path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reclaim_mod, "cancel_gate", racing_cancel_gate)

    outcome = _reclaim_one(record, now=deadline + 1, grace_seconds=300)

    assert outcome == "accepted_unfinished"
    assert settled == []
    assert not (result.bundle_path / CANCELLATION_FILENAME).exists()


def test_reclaim_expired_grace_yields_to_a_racing_completion(
    gate_shell_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response published between reclaim's check and its locked cancel wins."""
    result = create_gate(gate_spec(request_id="race-grace", timeout=1.0))
    record = _record_for_bundle(result.bundle_path, gate_id="race-grace")
    settled = _settlement_recorder(monkeypatch)
    deadline = _gate_deadline(result.bundle_path)

    def racing_cancel_gate(bundle_path: Path, **kwargs: object) -> dict[str, object]:
        from sase.notification_gates.executor import execute_gate_selection

        execute_gate_selection(bundle_path, ["accept"], {})
        return real_cancel_gate(bundle_path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reclaim_mod, "cancel_gate", racing_cancel_gate)

    outcome = _reclaim_one(record, now=deadline + 1000, grace_seconds=1)

    assert outcome == "answered"
    assert settled == [("race-grace", "answered", "gate answered")]


def test_reclaim_raises_on_a_receipt_naming_a_different_gate(
    gate_shell_home: Path, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME

    result = create_gate(gate_spec(request_id="contradictory-receipt"))
    accept_gate_decision(result.bundle_path, ["accept"], {})
    receipt_path = result.bundle_path / DECISION_RECEIPT_FILENAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["gate_id"] = "someone-elses-gate"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    record = _record_for_bundle(result.bundle_path, gate_id="contradictory-receipt")
    _settlement_recorder(monkeypatch)

    with pytest.raises(ValueError, match="invalid_gate_decision_receipt"):
        _reclaim_one(record, now=time.time(), grace_seconds=300)


_PROJECT = "proj"


class _Killed(BaseException):
    """Stands in for the SIGKILL that ends a chop mid-pass."""


def _settled_gate(
    timestamp: str, *, lane: str, changed_after_snapshot: bool = False
) -> str:
    """Create an answered gate shell whose metadata was last written an hour ago."""
    artifacts_dir = make_gate_shell(
        _PROJECT,
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
        / _PROJECT
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    artifacts_dir.mkdir(parents=True)
    meta = {"agent_family": lane, "name": f"{lane}{PLAN_CHAIN_CODER_SUFFIX}"}
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return str(artifacts_dir)


def _serve_index(
    monkeypatch: pytest.MonkeyPatch, artifacts_dirs: list[str]
) -> list[str | None]:
    """Serve *artifacts_dirs* as the artifact index, recording each full read."""
    patch_gate_shell_project_records(monkeypatch, artifacts_dirs)
    serve = store_mod.project_records
    reads: list[str | None] = []

    def read(project_name: str | None) -> list[AgentArtifactRecordWire]:
        reads.append(project_name)
        return serve(project_name)

    monkeypatch.setattr(store_mod, "project_records", read)
    return reads


def _serve_family_query(
    monkeypatch: pytest.MonkeyPatch, artifacts_dirs: tuple[str, ...] = ()
) -> list[tuple[str | None, str]]:
    """Replace the per-family index query, recording each call."""
    queries: list[tuple[str | None, str]] = []

    def query(project_name: str | None, family: str) -> list[AgentArtifactRecordWire]:
        queries.append((project_name, family))
        return [record_from_disk(artifacts_dir) for artifacts_dir in artifacts_dirs]

    monkeypatch.setattr(handoff_mod, "_family_records", query)
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

    def fake(*, project: str | None = None) -> GateShellSnapshot:
        index = len(reads)
        reads.append(project)
        dirs = dirs_by_read[min(index, len(dirs_by_read) - 1)]
        records = [record_from_disk(d) for d in dirs]
        members: dict[tuple[str, str], list[AgentArtifactRecordWire]] = {}
        for record in records:
            meta = record.agent_meta
            if meta is not None and meta.agent_family:
                key = (record.project_name, meta.agent_family)
                members.setdefault(key, []).append(record)
        return GateShellSnapshot(
            taken_at=taken_ats[min(index, len(taken_ats) - 1)],
            gate_shells=tuple(store_mod._gate_shells_from_records(records)),
            family_members={key: tuple(value) for key, value in members.items()},
            record_count=len(records),
        )

    monkeypatch.setattr(reclaim_mod, "load_gate_shell_snapshot", fake)
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
        evidence[str(meta["agent_family"])] = dict(successor_evidence)
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
    family_queries = _serve_family_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs()

    assert summary.scanned == 3
    assert index_reads == [None]
    assert family_queries == []
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
    family_queries = _serve_family_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs()

    assert summary.scanned == 1
    assert index_reads == [None, None]
    assert family_queries == []
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
    family_queries = _serve_family_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs()

    assert summary.scanned == 2
    assert reads == [None, None]
    assert family_queries == []
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
    family_queries = _serve_family_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    first = reconcile_incomplete_gate_handoffs()

    assert first.scanned == 0
    assert first.deferred == 1
    assert family_queries == []
    assert evidence == {}
    assert load_reconcile_cursor(_PROJECT) == {}

    second = reconcile_incomplete_gate_handoffs()

    assert second.scanned == 1
    assert second.deferred == 0


def test_reconcile_skips_a_refresh_when_it_would_not_fit_before_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _settled_gate("20260912000001", lane="lane", changed_after_snapshot=True)
    _serve_index(monkeypatch, [gate])
    family_queries = _serve_family_query(monkeypatch)
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs(
        deadline=100.0, clock=lambda: 50.0, snapshot_read_seconds=60.0
    )

    assert summary.scanned == 0
    assert summary.deferred == 1
    assert family_queries == []
    assert evidence == {}


def test_reconcile_defers_everything_when_its_deadline_has_already_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_index(monkeypatch, _settled_gates(3))
    _serve_family_query(monkeypatch)
    _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs(deadline=0.0, clock=lambda: 1.0)

    assert summary.scanned == 0
    assert summary.deferred == 3


def test_reclaim_and_reconcile_share_one_caller_provided_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = make_gate_shell(
        _PROJECT,
        "20260912000000",
        "lane--gate",
        lane="lane",
        gate_id="gate-pending",
        gate_state="pending",
    )
    settled = _settled_gate("20260912000001", lane="lane2")
    index_reads = _serve_index(monkeypatch, [pending, settled])
    family_queries = _serve_family_query(monkeypatch)
    _stub_decisions(monkeypatch)

    snapshot = store_mod.load_gate_shell_snapshot()
    reclaim_summary = reclaim_pending_gate_shells(snapshot=snapshot)
    reconcile_summary = reconcile_incomplete_gate_handoffs(snapshot=snapshot)

    assert index_reads == [None]
    # Settling the bundle-less pending gate as "lost" makes its own unrelated
    # follow-up-evidence query through handoff_launch.launch_or_record_followup,
    # outside the reconcile pass this test exercises.
    assert family_queries == [(_PROJECT, "lane")]
    assert reclaim_summary.scanned == 1
    assert reclaim_summary.lost == 1
    assert reconcile_summary.scanned == 1


def test_reconcile_saves_its_cursor_after_each_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gates = _settled_gates(3)
    _serve_index(monkeypatch, gates)
    _serve_family_query(monkeypatch)
    classified: list[None] = []

    def killed_on_third_gate() -> None:
        if len(classified) == 2:
            raise _Killed
        classified.append(None)

    _stub_decisions(monkeypatch, on_classify=killed_on_third_gate)

    with pytest.raises(_Killed):
        reconcile_incomplete_gate_handoffs()

    assert load_reconcile_cursor(_PROJECT) == {
        "timestamp": "20260912000001",
        "artifacts_dir": str(Path(gates[1]).resolve()),
    }


def test_reconcile_defers_gates_past_its_time_budget_then_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_index(monkeypatch, _settled_gates(3))
    _serve_family_query(monkeypatch)
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
