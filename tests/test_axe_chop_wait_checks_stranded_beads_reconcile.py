"""Stranded-bead reconciliation and collector tests.

Split from ``tests.test_axe_chop_wait_checks_stranded_beads``; the
original module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import sase.bead.stranded_facts as stranded_facts
import sase.scripts._chop_wait_checks_run as wait_checks_run
import sase.scripts._chop_wait_checks_stranded as stranded_cache
import sase.scripts._chop_wait_checks_terminal as wait_checks_terminal
from sase.bead.model import Status
from sase.core.agent_scan_wire import DoneMarkerWire
from sase.core.stranded_work_facade import StrandedWorkReport
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, load_notifications

from tests._axe_chop_wait_checks_helpers import run_wait_checks
from tests._axe_chop_wait_checks_stranded_beads_helpers import (
    STRANDED_BEAD_ID,
    STRANDED_PARENT_ID,
    capture_collection_targets,
    ensure_projects_dir,
    make_waiters,
    point_wait_bead_status,
    seed_stranded_notification,
    wire_targeted_collector,
)
from tests._stranded_collector_helpers import (
    PROJECT,
    child_plan,
    phase,
    record,
    wire_collector,
)

__all__ = [
    "test_closed_bead_absent_from_reducer_still_dismisses_outstanding_alert",
    "test_collection_failure_retains_outstanding_stranded_alert",
    "test_no_stranded_work_without_pending_waits_or_active_alerts",
    "test_notification_only_reconciliation_dismisses_resolved_states",
    "test_parse_stranded_bead_wait_dedup_key_ignores_malformed",
    "test_reconciliation_collects_only_pending_and_outstanding_ids",
    "test_status_read_failure_retains_outstanding_stranded_alert",
    "test_targeted_collector_loads_only_named_candidates_and_child_context",
    "test_targeted_report_cache_is_shared_across_ticks_and_invalidates",
]


def test_targeted_report_cache_is_shared_across_ticks_and_invalidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    monkeypatch.setattr(
        stranded_cache, "canonical_beads_dir_for_project", lambda _p: beads_dir
    )
    fingerprint = ["store-v1"]
    monkeypatch.setattr(
        stranded_cache.bead_read_facade,
        "store_fingerprint",
        lambda _path: SimpleNamespace(token=fingerprint[0]),
    )
    facts_calls: list[tuple[str, ...]] = []
    reduce_calls = 0

    def collect(project: str, *, now: float, bead_ids):
        facts_calls.append((project, *tuple(bead_ids)))
        return {"now": now, "beads": []}

    def reduce(_facts):
        nonlocal reduce_calls
        reduce_calls += 1
        return StrandedWorkReport()

    monkeypatch.setattr(stranded_cache, "collect_stranded_work_input", collect)
    monkeypatch.setattr(stranded_cache, "collect_issue_titles", lambda *_a, **_k: {})
    monkeypatch.setattr(stranded_cache, "reduce_stranded_work", reduce)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    stranded_cache.collect_targeted_stranded_report(
        "proj", ("sase-2", "sase-1"), now=100.0
    )
    for moment in range(101, 160):
        stranded_cache.collect_targeted_stranded_report(
            "proj", ("sase-1", "sase-2"), now=float(moment)
        )
    assert len(facts_calls) == 1
    assert reduce_calls == 1

    stranded_cache.collect_targeted_stranded_report(
        "proj", ("sase-1", "sase-2"), now=160.0
    )
    assert len(facts_calls) == 2
    fingerprint[0] = "store-v2"
    stranded_cache.collect_targeted_stranded_report(
        "proj", ("sase-1", "sase-2"), now=161.0
    )
    assert len(facts_calls) == 3
    assert reduce_calls == 3


def test_targeted_collector_loads_only_named_candidates_and_child_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "target-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, title="Target"),
        phase("sase-1.3", assignee="sase-1.3", title="Other"),
        child_plan("sase-1.2.plan", parent_id=STRANDED_BEAD_ID, title="Context"),
        child_plan("sase-1.3.plan", parent_id="sase-1.3", title="Other context"),
    ]
    wire_collector(
        monkeypatch,
        tmp_path,
        issues,
        [record(artifact, name=STRANDED_BEAD_ID, session=STRANDED_BEAD_ID)],
    )

    facts = stranded_facts.collect_stranded_work_input(
        PROJECT,
        now=time.time(),
        bead_ids=[STRANDED_BEAD_ID],
    )

    assert {item["id"] for item in facts["beads"]} == {
        STRANDED_BEAD_ID,
        "sase-1.2.plan",
    }
    assert stranded_facts.collect_issue_titles(
        PROJECT,
        bead_ids=[STRANDED_BEAD_ID],
    ) == {STRANDED_BEAD_ID: "Target", "sase-1.2.plan": "Context"}


def test_parse_stranded_bead_wait_dedup_key_ignores_malformed() -> None:
    parse = wait_checks_terminal._parse_stranded_bead_wait_dedup_key
    assert parse(f"wait_checks:stranded-bead:proj:{STRANDED_BEAD_ID}") == (
        "proj",
        STRANDED_BEAD_ID,
    )
    assert parse("wait_checks:stranded-bead:proj") is None
    assert parse("wait_checks:stranded-bead:") is None
    assert parse("wait_checks:terminal-blocked:/tmp/waiter") is None
    assert parse("other:stranded-bead:proj:sase-1") is None
    assert parse(None) is None


@pytest.mark.parametrize("state", ["settling", "owned", "delegated"])
def test_notification_only_reconciliation_dismisses_resolved_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "active-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID)
    ]
    if state == "settling":
        records = [
            record(
                artifact,
                name=STRANDED_BEAD_ID,
                session=STRANDED_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 30),
            )
        ]
    elif state == "owned":
        records = [
            record(
                artifact,
                name=STRANDED_BEAD_ID,
                session=STRANDED_BEAD_ID,
                pid=os.getpid(),
            )
        ]
    else:
        from sase.agent.pending_handoff import PLAN_PENDING_MARKER

        (artifact / PLAN_PENDING_MARKER).write_text("", encoding="utf-8")
        records = [
            record(
                artifact,
                name=STRANDED_BEAD_ID,
                session=STRANDED_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
            )
        ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    ensure_projects_dir(tmp_path)
    seed_stranded_notification("proj", STRANDED_BEAD_ID)

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []


def test_closed_bead_absent_from_reducer_still_dismisses_outstanding_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, status=Status.CLOSED)]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    ensure_projects_dir(tmp_path)
    seed_stranded_notification("proj", STRANDED_BEAD_ID)
    calls = capture_collection_targets(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []
    assert calls == []


def test_status_read_failure_retains_outstanding_stranded_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, status=Status.CLOSED)]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    ensure_projects_dir(tmp_path)
    seed_stranded_notification("proj", STRANDED_BEAD_ID)
    monkeypatch.setattr(
        wait_checks_run,
        "bead_statuses_for_project",
        lambda *_args, **_kwargs: None,
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert len(load_notifications()) == 1


def test_collection_failure_retains_outstanding_stranded_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID)
    ]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    ensure_projects_dir(tmp_path)
    seed_stranded_notification("proj", STRANDED_BEAD_ID)

    def fail(*_args, **_kwargs):
        raise OSError("index unavailable")

    monkeypatch.setattr(wait_checks_run, "collect_targeted_stranded_report", fail)
    run_wait_checks(tmp_path, monkeypatch)

    assert len(load_notifications()) == 1


def test_no_stranded_work_without_pending_waits_or_active_alerts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_calls: list[object] = []
    collect_calls: list[object] = []

    def record_status(*args: object, **kwargs: object) -> dict[str, str]:
        status_calls.append((args, kwargs))
        return {}

    def record_collect(*args: object, **kwargs: object) -> None:
        collect_calls.append((args, kwargs))

    monkeypatch.setattr(wait_checks_run, "bead_statuses_for_project", record_status)
    monkeypatch.setattr(
        wait_checks_run,
        "collect_targeted_stranded_report",
        record_collect,
    )
    ensure_projects_dir(tmp_path)

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []
    assert status_calls == []
    assert collect_calls == []


def test_reconciliation_collects_only_pending_and_outstanding_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    other_id = "sase-9"
    issues = [
        phase(
            STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID
        ),
        phase(other_id, assignee=other_id, parent_id="sase-8"),
        phase("sase-1.3", assignee="sase-1.3", parent_id=STRANDED_PARENT_ID),
    ]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    make_waiters(tmp_path, "waiter")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    seed_stranded_notification("other-proj", other_id)
    append_notification(
        Notification(
            id=str(uuid4()),
            timestamp="2026-10-26T00:00:00+00:00",
            sender="wait_checks",
            notes=["malformed"],
            tags=["wait", "blocked", "stranded"],
            dedup_key="wait_checks:stranded-bead:proj",
        )
    )
    append_notification(
        Notification(
            id=str(uuid4()),
            timestamp="2026-10-26T00:00:00+00:00",
            sender="wait_checks",
            notes=["unrelated"],
            tags=["wait", "blocked"],
            dedup_key="wait_checks:terminal-blocked:/tmp/waiter",
        )
    )
    append_notification(
        Notification(
            id=str(uuid4()),
            timestamp="2026-10-26T00:00:00+00:00",
            sender="other",
            notes=["wrong sender"],
            tags=["stranded"],
            dedup_key=f"wait_checks:stranded-bead:proj:{STRANDED_BEAD_ID}",
        )
    )
    calls = capture_collection_targets(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert sorted(calls) == [
        ("other-proj", (other_id,)),
        ("proj", (STRANDED_BEAD_ID,)),
    ]
    assert any(
        row.dedup_key == f"wait_checks:stranded-bead:proj:{STRANDED_BEAD_ID}"
        for row in load_notifications()
        if row.sender == "wait_checks"
    )
