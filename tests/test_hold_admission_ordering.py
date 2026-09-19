"""Deterministic hold-publication vs admission-transition ordering."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
from threading import Event, Thread, current_thread
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_admission_engine import AdmissionEngine
from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.core.agent_hold_facade import (
    arm_agent_hold,
    list_current_agent_holds,
    release_agent_hold,
    snapshot_active_agent_holds,
)
from sase.core.agent_hold_store import agent_hold_store_path
from sase.core.agent_hold_types import PendingCapture
from sase.core.runner_slots import runner_slot_admission_lock
from sase.notifications.store import load_notifications
from tests._launch_admission_helpers import plan as _plan
from tests._launch_admission_helpers import proc_unit as _proc_unit
from tests._runner_slot_fixtures import artifact


pytest.importorskip("sase_core_rs")


def _cli_armer(key: str) -> dict[str, Any]:
    return {
        "kind": "cli",
        "key": key,
        "display": key,
        "project": "proj",
        "pid": os.getpid(),
    }


@contextmanager
def _isolated_home(tmp_path: Path) -> Iterator[None]:
    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=4),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        yield


def _claim(
    waiter: Path,
    *,
    name: str = "target.agent--code",
) -> tuple[str | None, bool]:
    return run_agent_wait_slots._try_claim_runner_slot(
        artifacts_dir=str(waiter),
        cl_name="cl",
        timestamp=waiter.name,
        directive_threshold=None,
        agent_meta={"name": name},
        claim=lambda: "started",
    )


def test_arm_before_claim_parks_the_candidate(tmp_path: Path) -> None:
    waiter = artifact(tmp_path, "20260918120000", 801)
    with _isolated_home(tmp_path):
        arm_agent_hold(
            armer=_cli_armer("cli:arm-first"),
            names=["target.agent--code"],
            scope="host",
            ttl_seconds=60.0,
        )
        started, parked = _claim(waiter)

    assert started is None
    assert parked
    assert (waiter / "waiting.json").exists()


def test_claim_then_arm_does_not_reblock_running_work(tmp_path: Path) -> None:
    running = artifact(tmp_path, "20260918120001", 802)
    later = artifact(tmp_path, "20260918120002", 803)
    with _isolated_home(tmp_path):
        started, parked = _claim(running)
        assert started == "started"
        assert not parked
        arm_agent_hold(
            armer=_cli_armer("cli:arm-after"),
            names=["target.agent--code"],
            scope="host",
            ttl_seconds=60.0,
        )
        blocked, later_parked = _claim(later)

    assert not (running / "waiting.json").exists()
    assert blocked is None
    assert later_parked


def test_arm_between_snapshot_and_claim_cannot_publish_before_claim(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260918120003", 804)
    snapshot_taken = Event()
    arm_at_lock = Event()
    arm_finished = Event()
    original_snapshot = run_agent_wait_slots.snapshot_active_agent_holds
    original_lock = runner_slot_admission_lock
    claim_ident: dict[str, int | None] = {"id": None}

    def pausing_snapshot(*args: object, **kwargs: object) -> object:
        result = original_snapshot(*args, **kwargs)
        snapshot_taken.set()
        assert arm_at_lock.wait(timeout=5)
        assert not arm_finished.is_set()
        return result

    @contextmanager
    def instrumented_lock() -> Iterator[None]:
        if current_thread().ident != claim_ident["id"]:
            arm_at_lock.set()
        with original_lock():
            yield

    def arm() -> None:
        assert snapshot_taken.wait(timeout=5)
        arm_agent_hold(
            armer=_cli_armer("cli:race"),
            names=["target.agent--code"],
            scope="host",
            ttl_seconds=60.0,
        )
        arm_finished.set()

    started: dict[str, object] = {}

    def run_claim() -> None:
        claim_ident["id"] = current_thread().ident
        started["result"] = _claim(waiter)

    claim_thread = Thread(target=run_claim, name="claim-thread")
    arm_thread = Thread(target=arm, name="arm-thread")
    with _isolated_home(tmp_path):
        with (
            patch.object(
                run_agent_wait_slots,
                "snapshot_active_agent_holds",
                side_effect=pausing_snapshot,
            ),
            patch.object(
                run_agent_wait_slots,
                "runner_slot_admission_lock",
                instrumented_lock,
            ),
            patch(
                "sase.core.runner_slots.runner_slot_admission_lock",
                instrumented_lock,
            ),
        ):
            claim_thread.start()
            arm_thread.start()
            claim_thread.join(timeout=5)
            arm_thread.join(timeout=5)
        holds = list_current_agent_holds()

    assert not claim_thread.is_alive()
    assert not arm_thread.is_alive()
    assert started["result"] == ("started", False)
    assert arm_finished.is_set()
    assert not (waiter / "waiting.json").exists()
    assert any(hold["armer"]["key"] == "cli:race" for hold in holds)


def test_multiple_holds_release_independently(tmp_path: Path) -> None:
    waiter = artifact(tmp_path, "20260918120004", 805)
    with _isolated_home(tmp_path):
        first = arm_agent_hold(
            armer=_cli_armer("cli:one"),
            names=["target.agent--code"],
            scope="host",
            ttl_seconds=60.0,
        )
        second = arm_agent_hold(
            armer=_cli_armer("cli:two"),
            names=["target.agent--code"],
            scope="host",
            ttl_seconds=60.0,
        )
        blocked, parked = _claim(waiter)
        assert blocked is None
        assert parked
        assert release_agent_hold(first.record["armer"]["key"])
        still_blocked, _ = _claim(waiter)
        assert still_blocked is None
        assert release_agent_hold(second.record["armer"]["key"])
        admitted, parked_again = _claim(waiter)

    assert admitted == "started"
    assert not parked_again


def test_malformed_hold_store_fails_open_on_claim(tmp_path: Path) -> None:
    waiter = artifact(tmp_path, "20260918120005", 806)
    with _isolated_home(tmp_path):
        store = agent_hold_store_path()
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text("{not-json", encoding="utf-8")
        started, parked = _claim(waiter)

    assert started == "started"
    assert not parked


def test_pending_capture_runs_outside_runner_slot_lock(tmp_path: Path) -> None:
    captured = Event()
    release_holder = Event()
    holder_ready = Event()

    def holder() -> None:
        with runner_slot_admission_lock():
            holder_ready.set()
            release_holder.wait(timeout=5)

    def fake_capture(*, project: str | None) -> PendingCapture:
        del project
        assert holder_ready.is_set()
        assert not release_holder.is_set()
        captured.set()
        return PendingCapture(
            artifact_dirs=(),
            waiting_count=0,
            queued_count=0,
            skipped_running_count=0,
        )

    holder_thread = Thread(target=holder, daemon=True)
    with _isolated_home(tmp_path):
        holder_thread.start()
        assert holder_ready.wait(timeout=5)
        with patch(
            "sase.core.agent_hold_facade._capture_pending_targets",
            side_effect=fake_capture,
        ):
            arm_thread = Thread(
                target=lambda: arm_agent_hold(
                    armer=_cli_armer("cli:pending"),
                    names=["target.agent--code"],
                    pending=True,
                    scope="host",
                    ttl_seconds=60.0,
                ),
                daemon=True,
            )
            arm_thread.start()
            assert captured.wait(timeout=5)
            release_holder.set()
            arm_thread.join(timeout=5)
            holder_thread.join(timeout=5)

    assert captured.is_set()
    assert not arm_thread.is_alive()


def test_arm_notification_is_sent_outside_admission_lock(tmp_path: Path) -> None:
    depth = {"n": 0, "max": 0}
    notified_while_held: list[int] = []
    original_lock = runner_slot_admission_lock

    @contextmanager
    def tracking_lock() -> Iterator[None]:
        depth["n"] += 1
        depth["max"] = max(depth["max"], depth["n"])
        try:
            with original_lock():
                yield
        finally:
            depth["n"] -= 1

    def tracking_notify(*args: object, **kwargs: object) -> None:
        del args, kwargs
        notified_while_held.append(depth["n"])

    with (
        _isolated_home(tmp_path),
        patch(
            "sase.core.runner_slots.runner_slot_admission_lock",
            tracking_lock,
        ),
        patch(
            "sase.core.agent_hold_facade.upsert_hold_armed_notification",
            tracking_notify,
        ),
    ):
        arm_agent_hold(
            armer=_cli_armer("cli:notify"),
            names=["target.agent--code"],
            scope="host",
            ttl_seconds=60.0,
        )

    assert depth["max"] == 1
    assert notified_while_held == [0]


def test_snapshot_active_agent_holds_does_not_notify(tmp_path: Path) -> None:
    with _isolated_home(tmp_path):
        arm_agent_hold(
            armer=_cli_armer("cli:snap"),
            names=["target.agent--code"],
            scope="host",
            ttl_seconds=60.0,
        )
        before_notify = load_notifications()
        before, after = snapshot_active_agent_holds()
        after_notify = load_notifications()

    assert before
    assert after
    assert [hold["armer"]["key"] for hold in after] == ["cli:snap"]
    assert len(after_notify) == len(before_notify)


def test_stale_proc_dispatch_action_rechecks_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.core.agent_hold_facade._project_for_cwd", lambda: "sase")
    dispatched: list[str] = []
    engine = AdmissionEngine(
        plan=_plan(_proc_unit("unit-1", tmp_path, shell_name="checks")),
        admission_dir=tmp_path / "admission",
        request_id="req-stale-proc",
        proc_dispatcher=lambda unit, fingerprint: (
            dispatched.append(str(fingerprint)) or (True, "proc-1", None, [])
        ),
    )
    engine.admission_dir.mkdir(parents=True)
    arm_agent_hold(
        armer=_cli_armer("cli:proc-stale"),
        names=["checks"],
        scope="host",
        ttl_seconds=60.0,
    )
    outcome = engine._apply_action(
        {
            "kind": "dispatch",
            "logical_id": "unit-1",
            "unit_kind": "proc",
            "fingerprint": "fp-stale",
        }
    )

    assert outcome == "blocked"
    assert dispatched == []


def test_committed_proc_dispatch_is_immune_to_later_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.core.agent_hold_facade._project_for_cwd", lambda: "sase")
    dispatched: list[str] = []
    engine = AdmissionEngine(
        plan=_plan(_proc_unit("unit-1", tmp_path, shell_name="checks")),
        admission_dir=tmp_path / "admission",
        request_id="req-committed-proc",
        proc_dispatcher=lambda unit, fingerprint: (
            dispatched.append(str(fingerprint)) or (True, "proc-1", None, [])
        ),
    )
    engine.admission_dir.mkdir(parents=True)
    first = engine._apply_action(
        {
            "kind": "dispatch",
            "logical_id": "unit-1",
            "unit_kind": "proc",
            "fingerprint": "fp-commit",
        }
    )
    assert first is None
    assert dispatched == ["fp-commit"]
    arm_agent_hold(
        armer=_cli_armer("cli:proc-late"),
        names=["checks"],
        scope="host",
        ttl_seconds=60.0,
    )
    progress = engine.run(until_blocked=False)

    assert progress.complete
    assert dispatched == ["fp-commit"]


def test_arm_during_proc_commit_window_cannot_publish_before_dispatching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.core.agent_hold_facade._project_for_cwd", lambda: "sase")
    recheck_done = Event()
    arm_at_lock = Event()
    arm_finished = Event()
    dispatched: list[str] = []
    from sase.agent.launch_admission_engine_holds import proc_unit_blocked_by_hold

    original_recheck = proc_unit_blocked_by_hold
    original_lock = runner_slot_admission_lock
    dispatch_ident: dict[str, int | None] = {"id": None}

    def pausing_recheck(*args: object, **kwargs: object) -> bool:
        blocked = original_recheck(*args, **kwargs)
        recheck_done.set()
        assert arm_at_lock.wait(timeout=5)
        assert not arm_finished.is_set()
        return blocked

    @contextmanager
    def instrumented_lock() -> Iterator[None]:
        if current_thread().ident != dispatch_ident["id"]:
            arm_at_lock.set()
        with original_lock():
            yield

    def arm() -> None:
        assert recheck_done.wait(timeout=5)
        arm_agent_hold(
            armer=_cli_armer("cli:proc-race"),
            names=["checks"],
            scope="host",
            ttl_seconds=60.0,
        )
        arm_finished.set()

    engine = AdmissionEngine(
        plan=_plan(_proc_unit("unit-1", tmp_path, shell_name="checks")),
        admission_dir=tmp_path / "admission",
        request_id="req-proc-race",
        proc_dispatcher=lambda unit, fingerprint: (
            dispatched.append(str(fingerprint)) or (True, "proc-1", None, [])
        ),
    )
    engine.admission_dir.mkdir(parents=True)
    outcome: dict[str, object] = {}

    def dispatch() -> None:
        dispatch_ident["id"] = current_thread().ident
        outcome["result"] = engine._apply_action(
            {
                "kind": "dispatch",
                "logical_id": "unit-1",
                "unit_kind": "proc",
                "fingerprint": "fp-race",
            }
        )

    dispatch_thread = Thread(target=dispatch, name="proc-dispatch")
    arm_thread = Thread(target=arm, name="proc-arm")
    with (
        patch(
            "sase.agent.launch_admission_engine.proc_unit_blocked_by_hold",
            side_effect=pausing_recheck,
        ),
        patch(
            "sase.agent.launch_admission_engine.runner_slot_admission_lock",
            instrumented_lock,
        ),
        patch(
            "sase.core.runner_slots.runner_slot_admission_lock",
            instrumented_lock,
        ),
    ):
        dispatch_thread.start()
        arm_thread.start()
        dispatch_thread.join(timeout=5)
        arm_thread.join(timeout=5)

    assert not dispatch_thread.is_alive()
    assert not arm_thread.is_alive()
    assert outcome["result"] is None
    assert dispatched == ["fp-race"]
    assert arm_finished.is_set()
