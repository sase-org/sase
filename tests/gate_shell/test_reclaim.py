"""Result-contract coverage for gate-shell reclaim sweeps."""

from __future__ import annotations

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
    reclaim_pending_gate_shells,
    reconcile_incomplete_gate_handoffs,
)
from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX
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
        "errors": 1,
    }
    assert "error_details" not in payload


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
    serve = store_mod._project_records
    reads: list[str | None] = []

    def read(project_name: str | None) -> list[AgentArtifactRecordWire]:
        reads.append(project_name)
        return serve(project_name)

    monkeypatch.setattr(store_mod, "_project_records", read)
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


def test_reconcile_requeries_evidence_for_a_gate_changed_after_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _settled_gate("20260912000001", lane="lane", changed_after_snapshot=True)
    successor = _coder_successor("20260912000002", lane="lane")
    _serve_index(monkeypatch, [gate])
    family_queries = _serve_family_query(monkeypatch, (successor,))
    evidence = _stub_decisions(monkeypatch)

    summary = reconcile_incomplete_gate_handoffs()

    assert summary.scanned == 1
    assert family_queries == [(_PROJECT, "lane")]
    assert evidence["lane"]["attached_agent"] == f"lane{PLAN_CHAIN_CODER_SUFFIX}"


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
