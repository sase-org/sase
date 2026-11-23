"""Reuse stable stranded facts while refreshing liveness on TTL boundaries."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.models import agent_stranded
from sase.agent.handoff_inflight import HANDOFF_INFLIGHT_MARKER
from sase.bead import _stranded_facts_beads as beads
from sase.bead import _stranded_facts_collect as collect
from sase.bead import _stranded_facts_members as members
from sase.bead import _stranded_facts_snapshot as snapshot
from sase.bead import stranded as stranded_module
from sase.bead import stranded_facts as facts
from sase.bead.stranded import load_stranded_report
from sase.bead.stranded_facts import collect_stranded_work_snapshot
from sase.core.agent_scan_wire import (
    DoneMarkerWire,
    FinalizerStatusSummaryWire,
    WaitingMarkerWire,
)
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    epic,
    phase,
    record,
    wire_collector,
)
from tests.test_stranded_staged_handoff import (
    _done_records,
    _write_plan_record,
    _write_receipt,
)

_NOW = 1_700_000_000.0
_PID = os.getpid()
_STARTED = "2026-10-22T12:00:00-04:00"
_OLD_STARTED = "2023-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _clear_stranded_cache():
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def _fingerprint(token: str) -> SimpleNamespace:
    return SimpleNamespace(token=token)


def _wrap_snapshot(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    original = snapshot.stranded_snapshot
    calls: list[int] = []

    def wrapped(beads_dir: Path, bead_ids: object = None):
        calls.append(1)
        return original(beads_dir, bead_ids)

    monkeypatch.setattr(snapshot, "stranded_snapshot", wrapped)
    return calls


def _pin_fingerprint(monkeypatch: pytest.MonkeyPatch, tokens: list[str]) -> None:
    monkeypatch.setattr(
        snapshot, "store_fingerprint", lambda _beads_dir: _fingerprint(tokens[0])
    )


def _report(bead_id: str = "sase-demo.1") -> stranded_module.StrandedReport:
    return stranded_module.StrandedReport(
        report=StrandedWorkReport(
            verdicts=(
                StrandedWorkVerdict(
                    bead_id=bead_id,
                    kind="phase",
                    state="stranded",
                    blocked_by=(),
                ),
            ),
            stranded_ids=(bead_id,),
        ),
        titles={bead_id: "Phase"},
        generated_at=1.0,
        collection_failed=False,
        stable_rebuild=True,
    )


def test_unchanged_store_reuses_snapshot_and_refreshes_process_death(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    live = [True]
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                pid=_PID,
                run_started_at=_OLD_STARTED,
            )
        ],
    )
    _pin_fingerprint(monkeypatch, ["store-1"])
    calls = _wrap_snapshot(monkeypatch)
    monkeypatch.setattr(members, "_process_live", lambda _record: live[0])

    owned = load_stranded_report(PROJECT, now=_NOW)
    assert owned.stable_rebuild is True
    assert owned.collection_failed is False
    verdict = next(item for item in owned.report.verdicts if item.bead_id == "sase-1.2")
    assert verdict.state == "owned"
    assert calls == [1]

    live[0] = False
    refreshed = load_stranded_report(PROJECT, now=_NOW)
    assert refreshed.stable_rebuild is False
    lost = next(
        item for item in refreshed.report.verdicts if item.bead_id == "sase-1.2"
    )
    assert lost.state == "stranded"
    assert lost.reason == "lost"
    assert calls == [1]
    assert owned.titles == refreshed.titles


def test_pid_identity_change_with_unchanged_files_is_not_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                pid=_PID,
                run_started_at=_OLD_STARTED,
            )
        ],
    )
    _pin_fingerprint(monkeypatch, ["store-1"])
    calls = _wrap_snapshot(monkeypatch)
    monkeypatch.setattr(members, "record_is_live", lambda _record: False)

    first = load_stranded_report(PROJECT, now=_NOW)
    second = load_stranded_report(PROJECT, now=_NOW)
    assert calls == [1]
    assert first.stable_rebuild is True
    assert second.stable_rebuild is False
    member = bead_facts(
        facts.collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2"
    )["members"][0]
    assert member["process_live"] is False
    verdict = next(
        item for item in second.report.verdicts if item.bead_id == "sase-1.2"
    )
    assert verdict.state == "stranded"


def test_time_only_settle_grace_expiry_reuses_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    ended = _NOW - 5.0
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                done=DoneMarkerWire(outcome="completed", finished_at=ended),
            )
        ],
    )
    _pin_fingerprint(monkeypatch, ["store-1"])
    calls = _wrap_snapshot(monkeypatch)

    settling = load_stranded_report(PROJECT, now=ended + 10.0)
    expired = load_stranded_report(PROJECT, now=ended + 121.0)
    assert calls == [1]
    assert settling.stable_rebuild is True
    assert expired.stable_rebuild is False
    settle_verdict = next(
        item for item in settling.report.verdicts if item.bead_id == "sase-1.2"
    )
    expired_verdict = next(
        item for item in expired.report.verdicts if item.bead_id == "sase-1.2"
    )
    assert settle_verdict.state == "settling"
    assert expired_verdict.state == "stranded"


def test_queued_to_live_transition_reuses_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    queued = record(
        artifact,
        name="sase-1.2",
        session="sase-1.2",
        waiting=WaitingMarkerWire(
            waiting_for=["slot"], slot_requested_at="2026-01-01T00:00:00Z"
        ),
    )
    records = [queued]
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        records,
    )
    _pin_fingerprint(monkeypatch, ["store-1"])
    calls = _wrap_snapshot(monkeypatch)

    first = load_stranded_report(PROJECT, now=_NOW)
    member = bead_facts(
        facts.collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2"
    )["members"][0]
    assert member["lifecycle"] == "queued"

    records[0] = record(
        artifact,
        name="sase-1.2",
        session="sase-1.2",
        pid=_PID,
        run_started_at=_STARTED,
    )
    second = load_stranded_report(PROJECT, now=_NOW)
    live_member = bead_facts(
        facts.collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2"
    )["members"][0]
    assert calls == [1]
    assert first.stable_rebuild is True
    assert second.stable_rebuild is False
    assert live_member["lifecycle"] == "running"
    assert live_member["process_live"] is True


def test_delivered_handoff_and_finalizer_and_recovery_refresh_without_rebuild(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_plan_record(artifact)
    records = _done_records(artifact)
    meta = records[0].agent_meta
    assert meta is not None
    records[0] = replace(
        records[0],
        agent_meta=replace(
            meta, finalizer_status=FinalizerStatusSummaryWire(phase="declaring")
        ),
    )
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        records,
    )
    _pin_fingerprint(monkeypatch, ["store-1"])
    calls = _wrap_snapshot(monkeypatch)
    inflight = [True]
    monkeypatch.setattr(members, "recovery_in_flight", lambda _path: inflight[0])

    first = load_stranded_report(PROJECT, now=_NOW)
    member = bead_facts(
        facts.collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2"
    )["members"][0]
    assert member["finalizing"] is True
    assert member["recovery_in_flight"] is True
    assert member["staged_handoff"] == "plan"
    assert first.report.verdicts[0].state == "owned"

    records[0] = replace(
        records[0], agent_meta=replace(records[0].agent_meta, finalizer_status=None)
    )
    inflight[0] = False
    _write_receipt(artifact, "adopted")
    (artifact / HANDOFF_INFLIGHT_MARKER).write_text("{}", encoding="utf-8")
    second_input = facts.collect_stranded_work_input(PROJECT, now=_NOW - 3600)
    member = bead_facts(second_input, "sase-1.2")["members"][0]
    assert member["finalizing"] is False
    assert member["recovery_in_flight"] is False
    assert member["handoff_inflight"] is True
    (artifact / HANDOFF_INFLIGHT_MARKER).unlink()
    third = load_stranded_report(PROJECT, now=_NOW - 3600)
    assert calls == [1]
    assert third.stable_rebuild is False
    assert third.titles == first.titles


def test_bead_assignment_change_rebuilds_stable_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    issues = [phase("sase-1.2", assignee="sase-1.2")]
    wire_collector(
        monkeypatch,
        tmp_path,
        issues,
        [record(artifact, name="sase-1.2", session="sase-1.2", pid=_PID)],
    )
    tokens = ["store-1"]
    _pin_fingerprint(monkeypatch, tokens)
    calls = _wrap_snapshot(monkeypatch)

    first = load_stranded_report(PROJECT, now=_NOW)
    issues[:] = [phase("sase-1.2", assignee="other-agent")]
    tokens[0] = "store-2"
    second = load_stranded_report(PROJECT, now=_NOW)
    assert calls == [1, 1]
    assert first.stable_rebuild is True
    assert second.stable_rebuild is True
    assert (
        bead_facts(facts.collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
            "assignee"
        ]
        == "other-agent"
    )


def test_bead_deletion_and_missing_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    issues = [phase("sase-1.2", assignee="sase-1.2")]
    wire_collector(
        monkeypatch,
        tmp_path,
        issues,
        [record(artifact, name="sase-1.2", session="sase-1.2", pid=_PID)],
    )
    tokens = ["store-1"]
    _pin_fingerprint(monkeypatch, tokens)
    calls = _wrap_snapshot(monkeypatch)
    load_stranded_report(PROJECT, now=_NOW)
    issues.clear()
    tokens[0] = "store-deleted"
    deleted = load_stranded_report(PROJECT, now=_NOW)
    assert calls == [1, 1]
    assert deleted.report.verdicts == ()
    assert deleted.titles == {}

    monkeypatch.setattr(collect, "canonical_beads_dir_for_project", lambda _p: None)
    payload, titles, rebuilt = collect_stranded_work_snapshot(PROJECT, now=_NOW)
    assert payload["beads"] == []
    assert titles == {}
    assert rebuilt is True


def test_uncertified_fingerprint_never_reuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [record(artifact, name="sase-1.2", session="sase-1.2", pid=_PID)],
    )
    monkeypatch.setattr(snapshot, "store_fingerprint", lambda _beads_dir: None)
    calls = _wrap_snapshot(monkeypatch)
    first = load_stranded_report(PROJECT, now=_NOW)
    second = load_stranded_report(PROJECT, now=_NOW)
    assert calls == [1, 1]
    assert first.stable_rebuild is True
    assert second.stable_rebuild is True


def test_snapshot_failure_does_not_install_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [record(artifact, name="sase-1.2", session="sase-1.2", pid=_PID)],
    )
    _pin_fingerprint(monkeypatch, ["store-1"])
    original = snapshot.stranded_snapshot
    calls: list[int] = []

    def boom(_beads_dir: Path, bead_ids: object = None) -> object:
        calls.append(1)
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(snapshot, "stranded_snapshot", boom)
    failed = load_stranded_report(PROJECT, now=_NOW)
    assert failed.collection_failed is True
    assert failed.stable_rebuild is True
    monkeypatch.setattr(snapshot, "stranded_snapshot", original)
    recovered = load_stranded_report(PROJECT, now=_NOW)
    assert recovered.collection_failed is False
    assert recovered.stable_rebuild is True
    assert calls == [1]


def test_collection_failure_does_not_install_empty_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(agent_stranded, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        agent_stranded, "_project_fingerprint", lambda _project: "store"
    )
    first = _report()
    loads: list[str] = []

    def load_report(project_key: str) -> stranded_module.StrandedReport:
        loads.append(project_key)
        if len(loads) == 2:
            return stranded_module.StrandedReport(
                report=StrandedWorkReport(),
                titles={},
                generated_at=2.0,
                collection_failed=True,
            )
        return first

    monkeypatch.setattr(stranded_module, "load_stranded_report", load_report)
    telemetry = {
        "stranded_heavy_resolutions": 0,
        "stranded_liveness_checks": 0,
    }
    agent_stranded.warm_stranded_work_reports(("demo",), telemetry=telemetry)
    cached = agent_stranded.cached_stranded_report("demo")
    assert cached is first
    assert telemetry["stranded_heavy_resolutions"] == 1

    now[0] = 200.0
    agent_stranded.warm_stranded_work_reports(("demo",), telemetry=telemetry)
    assert agent_stranded.cached_stranded_report("demo") is first
    assert loads == ["demo", "demo"]
    assert telemetry["stranded_heavy_resolutions"] == 1


def test_ttl_liveness_check_is_not_a_heavy_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(agent_stranded, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        agent_stranded, "_project_fingerprint", lambda _project: "store"
    )
    snapshot = _report()
    loads = 0

    def load(_project: str) -> stranded_module.StrandedReport:
        nonlocal loads
        loads += 1
        return stranded_module.StrandedReport(
            report=snapshot.report,
            titles=snapshot.titles,
            generated_at=float(loads),
            collection_failed=False,
            stable_rebuild=loads == 1,
        )

    monkeypatch.setattr(stranded_module, "load_stranded_report", load)
    telemetry: dict[str, int] = {}
    agent_stranded.warm_stranded_work_reports(("demo",), telemetry=telemetry)
    now[0] = 161.0
    agent_stranded.warm_stranded_work_reports(
        ("demo",), force=True, force_immediate=True, telemetry=telemetry
    )
    assert loads == 2
    assert telemetry["stranded_heavy_resolutions"] == 1
    assert telemetry["stranded_liveness_checks"] == 1


def test_forced_immediate_refresh_runs_during_cached_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(agent_stranded, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        agent_stranded, "_project_fingerprint", lambda _project: "store"
    )
    loads: list[str] = []

    def load(project_key: str) -> stranded_module.StrandedReport:
        loads.append(project_key)
        return stranded_module.StrandedReport(
            report=StrandedWorkReport(),
            titles={},
            generated_at=1.0,
            collection_failed=False,
            stable_rebuild=False,
        )

    monkeypatch.setattr(stranded_module, "load_stranded_report", load)
    agent_stranded.warm_stranded_work_reports(("demo",))
    agent_stranded.warm_stranded_work_reports(
        ("demo",), force=True, force_immediate=True
    )
    assert loads == ["demo", "demo"]


def test_measured_realistic_fixture_ttl_skips_stable_rebuild(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    issues = [phase(f"s.ph{index}", assignee=f"s.ph{index}") for index in range(80)]
    issues.append(epic("s.epic"))
    wire_collector(monkeypatch, tmp_path, issues, [])
    monkeypatch.setattr(beads, "session_record_cache", lambda _p, _k: {})
    _pin_fingerprint(monkeypatch, ["store-1"])
    calls = _wrap_snapshot(monkeypatch)

    cold_started = time.perf_counter()
    cold_payload, cold_titles, cold_rebuilt = collect_stranded_work_snapshot(
        PROJECT, now=_NOW
    )
    cold_elapsed = time.perf_counter() - cold_started
    warm_started = time.perf_counter()
    warm_payload, warm_titles, warm_rebuilt = collect_stranded_work_snapshot(
        PROJECT, now=_NOW + 60.0
    )
    warm_elapsed = time.perf_counter() - warm_started

    assert cold_rebuilt is True
    assert warm_rebuilt is False
    assert calls == [1]
    assert len(cold_payload["beads"]) == 81
    assert warm_payload["now"] == _NOW + 60.0
    assert warm_titles == cold_titles
    assert {bead["id"] for bead in warm_payload["beads"]} == {
        bead["id"] for bead in cold_payload["beads"]
    }
    assert warm_elapsed < cold_elapsed or warm_elapsed < 0.05
