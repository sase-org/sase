"""Crash-window recovery for staged monitor adoption.

A proc submitted before the member state flipped (or finished before the
outer receipt was written) must be adopted on retry, never resubmitted.
A fingerprint mismatch refuses without a second launch. A held cleanup
that settled the reserved run or released the prepared reservation is
repaired on retry by reacquiring the same logical reservation; a
canceled run is never reused and an ambiguous command never restarts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from sase.core.tool_run import tool_run_show
from sase.finalizers.prepare import (
    load_prepared_completion,
    persist_prepared_completion,
)
from sase.monitor.models import MonitorError
from sase.monitor.start_stage import (
    launch_from_persisted_payload,
    stage_monitor,
)
from sase.monitor.start_stage_adopt import _load_staged_monitor_launch_payload
from sase.monitor.staged_owner import launch_payload_path
from sase.procs.store import get_proc
from sase.procs.submission import ProcSubmitError
from tests.monitor._fixtures import wait_for_done

from ._start_stage import (
    read_reservations,
    sandbox_home as sandbox_home,
    sandbox_project,
    sealed_intent,
    stage_env,
    stage_request,
)

__all__ = [
    "test_active_proc_is_adopted_not_duplicated",
    "test_bound_intent_is_retained_across_retry",
    "test_concurrent_adopt_yields_one_proc",
    "test_discarded_stage_never_reacquires",
    "test_failed_claim_transfer_holds_without_second_proc",
    "test_finished_proc_is_reused_without_second_submit",
    "test_fingerprint_mismatch_refuses_without_second_launch",
    "test_held_cleanup_then_retry_reacquires_tool_run_and_prepared_intent",
    "test_store_unreadable_refuses_without_submit",
]


def _set_member_staged(artifacts_dir: str) -> None:
    """Reset the member state to staged after a launch attempt."""
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_state"] = "staged"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _meta(artifacts_dir: str) -> dict[str, Any]:
    return json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())


def _refuse_submit(*args: Any, **kwargs: Any) -> Any:
    del args, kwargs
    raise AssertionError("recovery must not submit a second proc")


def test_finished_proc_is_reused_without_second_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path, command="true"))
    dirs.append(staged.record.artifacts_dir)

    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    assert record.monitor_state == "running"
    wait_for_done(record.artifacts_dir, timeout=30.0)

    _set_member_staged(staged.record.artifacts_dir)
    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _refuse_submit)
    relaunched = launch_from_persisted_payload(staged.record.artifacts_dir)

    assert relaunched.monitor_id == staged.record.monitor_id
    assert relaunched.monitor_state == "running"
    assert get_proc(staged.record.monitor_id) is not None


def test_active_proc_is_adopted_not_duplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor.store import stop_monitor

    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path, command="sleep 30"))
    dirs.append(staged.record.artifacts_dir)

    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    assert record.monitor_state == "running"
    assert record.pid is not None
    deadline = time.monotonic() + 20.0
    while True:
        current = get_proc(staged.record.monitor_id)
        if (
            current is not None
            and current.status == "running"
            and current.pid is not None
        ):
            break
        assert time.monotonic() < deadline, "monitor proc never reached running"
        time.sleep(0.1)  # sase-test-wait: poll for supervisor claim of the staged proc
    try:
        _set_member_staged(staged.record.artifacts_dir)
        monkeypatch.setattr(
            "sase.monitor.start_launch.submit_proc_request", _refuse_submit
        )
        relaunched = launch_from_persisted_payload(staged.record.artifacts_dir)

        assert relaunched.monitor_id == staged.record.monitor_id
        assert relaunched.monitor_state == "running"
        assert relaunched.pid == record.pid
    finally:
        stop_monitor(record)
        wait_for_done(record.artifacts_dir, timeout=30.0)
        assert get_proc(staged.record.monitor_id) is not None


def test_fingerprint_mismatch_refuses_without_second_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path, command="true"))
    dirs.append(staged.record.artifacts_dir)

    launch_from_persisted_payload(staged.record.artifacts_dir)
    wait_for_done(staged.record.artifacts_dir, timeout=30.0)

    payload_path = launch_payload_path(staged.record.artifacts_dir)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["request_fingerprint"] = "tampered-fingerprint"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    _set_member_staged(staged.record.artifacts_dir)
    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _refuse_submit)
    with pytest.raises(MonitorError, match="fingerprint"):
        launch_from_persisted_payload(staged.record.artifacts_dir)


def test_store_unreadable_refuses_without_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path, command="true"))
    dirs.append(staged.record.artifacts_dir)

    def _fail_read(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise OSError("proc store unavailable")

    monkeypatch.setattr("sase.procs.store.get_proc", _fail_read)
    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _refuse_submit)
    with pytest.raises(MonitorError, match="could not read existing proc"):
        launch_from_persisted_payload(staged.record.artifacts_dir)


def test_discarded_stage_never_reacquires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.staged_handoff import read_staged_handoff
    from sase.monitor.start_stage import cleanup_staged_monitor

    root = sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        stage_request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    first_run_id = staged.record.tool_run_id
    assert first_run_id

    cleanup_staged_monitor(staged.record.artifacts_dir, held=False)
    assert read_staged_handoff(dirs[0]) is None

    with pytest.raises(MonitorError, match="canceled run"):
        launch_from_persisted_payload(staged.record.artifacts_dir)
    assert _meta(staged.record.artifacts_dir).get("monitor_tool_run_id") == (
        first_run_id
    )
    assert get_proc(staged.record.monitor_id) is None


def test_failed_claim_transfer_holds_without_second_proc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path, command="true"))
    dirs.append(staged.record.artifacts_dir)

    def _fail_claim(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return SimpleNamespace(
            result=SimpleNamespace(success=False, error="workspace gone"),
            starter_claim=None,
        )

    monkeypatch.setattr(
        "sase.monitor.start_launch.claim_monitor_workspace", _fail_claim
    )
    with pytest.raises(MonitorError, match="could not claim workspace"):
        launch_from_persisted_payload(staged.record.artifacts_dir)
    assert _meta(staged.record.artifacts_dir).get("monitor_stage_held") is True

    # The failed submit still recorded a terminal launch-failure row. The
    # retry adopts that row as the completed effect instead of running
    # the command a second time.
    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _refuse_submit)
    relaunched = launch_from_persisted_payload(staged.record.artifacts_dir)
    assert relaunched.monitor_id == staged.record.monitor_id


def test_held_cleanup_then_retry_reacquires_tool_run_and_prepared_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    prepared = persist_prepared_completion(
        sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
    )
    staged = stage_monitor(
        stage_request(
            tmp_path,
            command="just check",
            cwd=str(root),
            profile="verify",
            completion_ref=prepared.intent_ref,
        )
    )
    dirs.append(staged.record.artifacts_dir)
    first_run_id = staged.record.tool_run_id
    assert first_run_id

    def _fail_submit(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ProcSubmitError("ack failed")

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fail_submit)
    with pytest.raises(MonitorError, match="ack failed"):
        launch_from_persisted_payload(staged.record.artifacts_dir)

    assert _meta(staged.record.artifacts_dir).get("monitor_stage_held") is True
    shown = tool_run_show(first_run_id)["run"]
    assert shown["state"] not in {"created", "running"}
    diagnostics = shown.get("diagnostics") or []
    assert any("command was not run" in str(entry) for entry in diagnostics)
    assert not any("discarded" in str(entry) for entry in diagnostics)
    assert read_reservations(dirs[0]) == {}
    assert (
        load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])["status"]
        == "prepared"
    )

    fake_pid = os.getpid() + 10000

    def _fake_submit(
        *args: Any, after_spawn: Any, after_ack: Any, **kwargs: Any
    ) -> Any:
        del args, kwargs
        after_spawn(SimpleNamespace(pid=fake_pid))
        proc = SimpleNamespace(pid=fake_pid, supervisor_id="supervisor-fake")
        after_ack(proc)
        return proc

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fake_submit)
    monkeypatch.setattr(
        "sase.monitor.start_launch.claim_monitor_workspace",
        lambda *args, **kwargs: SimpleNamespace(
            result=SimpleNamespace(success=True), starter_claim=None
        ),
    )
    record = launch_from_persisted_payload(staged.record.artifacts_dir)

    assert record.monitor_state == "running"
    assert record.tool_run_id
    assert record.tool_run_id != first_run_id
    assert tool_run_show(record.tool_run_id)["run"]["state"] == "created"
    bound = load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])
    assert bound["status"] == "bound"
    assert bound["binding"]["monitor_id"] == staged.record.monitor_id
    reservations = read_reservations(dirs[0])
    assert reservations
    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    frozen_reservation = payload["resources"]["prepared_reservation"]
    assert frozen_reservation["staged_id"] == payload["staged_id"]
    assert any(
        record.get("reservation") == frozen_reservation
        for record in reservations.values()
        if isinstance(record, dict)
    )


def test_bound_intent_is_retained_across_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    prepared = persist_prepared_completion(
        sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
    )
    staged = stage_monitor(
        stage_request(
            tmp_path,
            command="just check",
            cwd=str(root),
            profile="verify",
            completion_ref=prepared.intent_ref,
        )
    )
    dirs.append(staged.record.artifacts_dir)

    fake_pid = os.getpid() + 10000

    def _fake_submit(
        *args: Any, after_spawn: Any, after_ack: Any, **kwargs: Any
    ) -> Any:
        del args, kwargs
        after_spawn(SimpleNamespace(pid=fake_pid))
        proc = SimpleNamespace(pid=fake_pid, supervisor_id="supervisor-fake")
        after_ack(proc)
        return proc

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fake_submit)
    monkeypatch.setattr(
        "sase.monitor.start_launch.claim_monitor_workspace",
        lambda *args, **kwargs: SimpleNamespace(
            result=SimpleNamespace(success=True), starter_claim=None
        ),
    )
    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    assert record.monitor_state == "running"
    assert (
        load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])["status"]
        == "bound"
    )

    # A crash after binding but before the member state flipped leaves the
    # intent bound to this monitor with no proc row (fake submit). The
    # retry retains that binding instead of failing or rebinding.
    _set_member_staged(staged.record.artifacts_dir)
    relaunched = launch_from_persisted_payload(staged.record.artifacts_dir)
    assert relaunched.monitor_state == "running"
    bound = load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])
    assert bound["status"] == "bound"
    assert bound["binding"]["monitor_id"] == staged.record.monitor_id


def test_concurrent_adopt_yields_one_proc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor.store import stop_monitor

    dirs = stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(stage_request(tmp_path, command="sleep 30"))
    dirs.append(staged.record.artifacts_dir)

    outcomes: list[Any] = []
    failures: list[BaseException] = []

    def _adopt() -> None:
        try:
            outcomes.append(launch_from_persisted_payload(staged.record.artifacts_dir))
        except BaseException as exc:  # noqa: BLE001 - re-raised below.
            failures.append(exc)

    threads = [threading.Thread(target=_adopt) for _ in range(2)]
    record = None
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120.0)
        assert not any(thread.is_alive() for thread in threads)
        assert not failures
        assert len(outcomes) == 2
        assert {item.monitor_id for item in outcomes} == {staged.record.monitor_id}
        assert {item.monitor_state for item in outcomes} == {"running"}
        assert get_proc(staged.record.monitor_id) is not None
        record = outcomes[0]
    finally:
        if record is not None:
            stop_monitor(record)
            wait_for_done(record.artifacts_dir, timeout=30.0)
