"""Receiver launch receipts keep booting monitor follow-ups out of the fence."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

import sase.monitor.followup as followup_module
from sase.monitor.continuation_delivery import (
    adopt_ordinary_continuation_delivery,
    claim_ordinary_continuation_dispatch,
    continuation_delivery_env,
)
from sase.monitor.delivery import (
    delivery_key,
    load_delivery_record,
    load_delivery_records,
    update_delivery_workspace,
)
from sase.monitor.delivery_receipts import (
    load_receiver_launch,
    receiver_launch_alive,
    _receiver_launch_path,
    _record_receiver_launch,
)
from sase.monitor.models import MonitorRecord
from sase.monitor.resume import reconcile_terminal_delivery, resume_monitor
from sase.monitor.resume_adoption import receiver_is_live

from ._resume_fixtures import (
    DEAD_RECEIVER_PID,
    _fake_spawn,
    _sandbox_home as _sandbox_home,
    _terminal_monitor,
)

_STALE_REASON = (
    "receiver ownership is ambiguous: dispatching receiver acme--1 has no live process"
)


def _dispatching_failed_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, MonitorRecord, dict[str, str]]:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    claim = claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    assert claim.spawn is True
    return monitor_dir, record, claim.key


def test_reconcile_keeps_booting_receiver_with_live_launch_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a spawned-but-unbooted receiver must not be fenced."""
    monitor_dir, record, key = _dispatching_failed_branch(tmp_path, monkeypatch)
    # Settlement order: receipt first, then the workspace mark. No ``acme--1``
    # artifact exists yet, so name resolution cannot find the receiver.
    _record_receiver_launch(
        monitor_dir,
        key,
        identity="acme--1",
        pid=os.getpid(),
        receiver_artifacts_dir=None,
    )
    update_delivery_workspace(monitor_dir, key, workspace_identity=str(tmp_path))
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    result = reconcile_terminal_delivery(record)

    assert result is not None
    assert result.ownership_outcome == "existing_receiver"
    assert result.spawned is False
    assert result.agent_name == "acme--1"
    assert captured == []
    stored = load_delivery_record(monitor_dir, key)
    assert stored is not None
    assert stored["disposition"] == "dispatching"

    adopted = adopt_ordinary_continuation_delivery(
        env=continuation_delivery_env(monitor_dir, key, "acme--1")
    )
    assert adopted is not None
    assert adopted["disposition"] == "acknowledged"
    assert adopted["acknowledged_by"] == "acme--1"


@pytest.mark.parametrize("variant", ["reaped_pid", "other_identity"])
def test_reconcile_fences_receiver_whose_launch_receipt_proves_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    # Start the child before the fixture fakes ``subprocess.Popen``.
    child = subprocess.Popen(["sleep", "30"]) if variant == "reaped_pid" else None
    try:
        monitor_dir, record, key = _dispatching_failed_branch(tmp_path, monkeypatch)
    except BaseException:
        if child is not None:
            child.kill()
            child.wait()
        raise
    if child is not None:
        try:
            _record_receiver_launch(
                monitor_dir,
                key,
                identity="acme--1",
                pid=child.pid,
                receiver_artifacts_dir=None,
            )
        finally:
            child.kill()
            child.wait()
    else:
        _record_receiver_launch(
            monitor_dir,
            key,
            identity="acme--2",
            pid=os.getpid(),
            receiver_artifacts_dir=None,
        )
    update_delivery_workspace(monitor_dir, key, workspace_identity=str(tmp_path))
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    assert reconcile_terminal_delivery(record) is None

    stored = load_delivery_record(monitor_dir, key)
    assert stored is not None
    assert stored["disposition"] == "needs_attention"
    assert stored["disposition_reason"] == _STALE_REASON
    assert captured == []


def test_followup_spawn_records_launch_receipt_before_workspace_mark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module,
        "spawn_agent_subprocess",
        _fake_spawn(captured, artifacts_dir="/tmp/acme--1-artifacts"),
    )
    receipt_present_at_mark: list[bool] = []

    def checked_update(
        artifacts_dir: str, key: dict[str, str], **kwargs: Any
    ) -> dict[str, Any] | None:
        receipt_present_at_mark.append(
            _receiver_launch_path(artifacts_dir, key).is_file()
        )
        return update_delivery_workspace(artifacts_dir, key, **kwargs)

    monkeypatch.setattr(
        "sase.monitor.delivery_receipts.update_delivery_workspace", checked_update
    )

    result = resume_monitor(record)

    assert result.spawned is True
    assert len(captured) == 1
    assert receipt_present_at_mark == [True]
    key = delivery_key(
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
    )
    receipt = load_receiver_launch(monitor_dir, key)
    assert receipt is not None
    assert receipt["identity"] == "acme--1"
    assert receipt["pid"] == DEAD_RECEIVER_PID
    assert receipt["receiver_artifacts_dir"] == "/tmp/acme--1-artifacts"
    assert receipt["key"] == key
    assert receiver_launch_alive(receipt, "acme--1") is False
    stored = load_delivery_record(monitor_dir, key)
    assert stored is not None
    assert stored["workspace_identity"]


def test_receipt_write_failure_does_not_fail_followup_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, _meta = _terminal_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    def broken_receipt(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(
        "sase.monitor.delivery_receipts._record_receiver_launch", broken_receipt
    )

    result = resume_monitor(record)

    assert result.spawned is True
    assert len(captured) == 1
    (stored,) = load_delivery_records(monitor_dir)
    assert stored["disposition"] == "dispatching"
    assert stored["workspace_identity"]


def test_record_receiver_launch_skips_unusable_pids(tmp_path: Path) -> None:
    key = {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"}
    for pid in (None, 0, -1, True, "123"):
        assert (
            _record_receiver_launch(
                tmp_path,
                key,
                identity="acme--1",
                pid=pid,
                receiver_artifacts_dir=None,
            )
            is None
        )
    assert not _receiver_launch_path(tmp_path, key).exists()
    assert load_receiver_launch(tmp_path, key) is None


def test_load_receiver_launch_tolerates_damaged_receipts(tmp_path: Path) -> None:
    key = {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"}
    path = _receiver_launch_path(tmp_path, key)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_receiver_launch(tmp_path, key) is None
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_receiver_launch(tmp_path, key) is None
    assert load_receiver_launch(tmp_path, {"monitor_id": "only"}) is None


def test_receipts_do_not_hide_from_delivery_record_scans(tmp_path: Path) -> None:
    key = {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"}
    claim_ordinary_continuation_dispatch(
        str(tmp_path),
        monitor_id="monitor-1",
        result_id="result-1",
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    _record_receiver_launch(
        tmp_path,
        key,
        identity="acme--1",
        pid=os.getpid(),
        receiver_artifacts_dir=None,
    )
    records = load_delivery_records(tmp_path)
    assert [item["key"] for item in records] == [key]


def test_receiver_is_live_consults_receipts_for_known_keys(tmp_path: Path) -> None:
    key = {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"}
    assert not receiver_is_live("", "acme--1", artifacts_dir=tmp_path, keys=[key])
    _record_receiver_launch(
        tmp_path,
        key,
        identity="acme--1",
        pid=os.getpid(),
        receiver_artifacts_dir=None,
    )
    assert receiver_is_live("", "acme--1", artifacts_dir=tmp_path, keys=[key])
    assert not receiver_is_live("", "acme--2", artifacts_dir=tmp_path, keys=[key])
    assert not receiver_is_live("", "acme--1")
