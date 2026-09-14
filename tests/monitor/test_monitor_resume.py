"""Manual monitor resume dispatch tests."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

import sase.monitor.followup as followup_module
from sase.feature_flags import override_flags
from sase.monitor.continuation_delivery import claim_ordinary_continuation_dispatch
from sase.monitor.delivery import load_delivery_record
from sase.monitor.models import MonitorRecord
from sase.monitor.resume import MonitorResumeError, resume_monitor

from ._fixtures import record_from_disk
from ._resume_fixtures import (
    _fake_spawn,
    _sandbox_home as _sandbox_home,
    _terminal_monitor,
)


def test_resume_uses_the_frozen_result_delivery_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    result = resume_monitor(record)

    assert result.spawned is True
    assert result.agent_name == "acme--1"
    assert len(captured) == 1
    delivery_key_payload = json.loads(
        captured[0]["extra_env"]["SASE_MONITOR_DELIVERY_KEY"]
    )
    assert delivery_key_payload == {
        "monitor_id": record.monitor_id,
        "result_id": meta["continuation_monitor_result_id"],
        "branch": "failed",
    }
    record_payload = load_delivery_record(monitor_dir, delivery_key_payload)
    assert record_payload is not None
    assert record_payload["disposition"] == "dispatching"
    on_disk = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert on_disk["monitor_followup_agent"] == "acme--1"
    assert on_disk["monitor_followup_outcome"] == "launched"


def test_resume_uses_persisted_record_protocol_when_rollout_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    with override_flags(monitor_continuation_records=False):
        result = resume_monitor(record)

    assert result.spawned is True
    assert result.agent_name == "acme--1"
    delivery_key_payload = json.loads(
        captured[0]["extra_env"]["SASE_MONITOR_DELIVERY_KEY"]
    )
    assert delivery_key_payload == {
        "monitor_id": record.monitor_id,
        "result_id": meta["continuation_monitor_result_id"],
        "branch": "failed",
    }
    record_payload = load_delivery_record(monitor_dir, delivery_key_payload)
    assert record_payload is not None
    assert record_payload["disposition"] == "dispatching"


def test_resume_does_not_retry_dispatching_record_without_uninvoked_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, meta = _terminal_monitor(tmp_path, monkeypatch)
    claim = claim_ordinary_continuation_dispatch(
        monitor_dir,
        monitor_id=record.monitor_id,
        result_id=meta["continuation_monitor_result_id"],
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    assert claim.record["disposition"] == "dispatching"
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        followup_module, "spawn_agent_subprocess", _fake_spawn(captured)
    )

    result = resume_monitor(record)

    assert result.spawned is False
    assert result.agent_name == "acme--1"
    assert result.ownership_outcome == "existing_receiver"
    assert captured == []
    payload = load_delivery_record(monitor_dir, claim.key)
    assert payload is not None
    assert payload["disposition"] == "dispatching"
    assert payload["reserved_identity"] == "acme--1"


def test_resume_rejects_fire_and_forget_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, record, _meta = _terminal_monitor(tmp_path, monkeypatch)
    meta_path = Path(monitor_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text())
    meta.pop("monitor_next_action", None)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    record = MonitorRecord.from_record(record_from_disk(monitor_dir))

    with pytest.raises(MonitorResumeError, match="fire-and-forget"):
        resume_monitor(record)


def test_resume_rejects_stopped_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _monitor_dir, record, _meta = _terminal_monitor(tmp_path, monkeypatch)
    record = replace(record, monitor_state="stopped")

    with pytest.raises(MonitorResumeError, match="inspection-only"):
        resume_monitor(record)
