"""Continuation-record rollout tests for :mod:`sase.monitor.followup`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.monitor.followup as followup_module
from sase.agent.launch_types import AgentLaunchResult
from sase.continuation_capture import (
    persist_monitor_result,
    persist_monitor_result_best_effort,
)
from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_FIELD,
    MONITOR_CONTINUATION_PROTOCOL_LEGACY,
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.feature_flags import override_flags
from sase.llm_provider.continuation_budget import MONITOR_CONTINUATION_ENV

from ._followup_fixtures import (
    _SETTLE_TIMEOUT,
    _capture_with_output,
    _fake_result,
    _promote_and_start_monitor,
    _sandbox_home as _sandbox_home,
)


def test_launch_followup_agent_uses_legacy_launcher_when_records_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with override_flags(monitor_continuation_records=False):
        monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
            tmp_path, monkeypatch
        )
        meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
        assert (
            meta[MONITOR_CONTINUATION_PROTOCOL_FIELD]
            == MONITOR_CONTINUATION_PROTOCOL_LEGACY
        )
        meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
        capture = _capture_with_output(monitor_dir, "hello world\n")

        captured: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured.update(kwargs)
            return _fake_result()

        monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

        result = followup_module.launch_followup_agent(
            monitor_dir,
            meta,
            monitor_state="completed",
            exit_code=0,
            elapsed_seconds=1.5,
            capture=capture,
            project_name="proj",
            settle_timeout_seconds=_SETTLE_TIMEOUT,
        )

    assert result.launched is True
    assert meta["monitor_followup_agent"] == "acme--1"
    assert MONITOR_CONTINUATION_ENV not in captured["extra_env"]
    assert "continuation_monitor_result_id" not in meta
    assert not (Path(monitor_dir) / "continuation" / "delivery").exists()


def test_enabled_start_keeps_versioned_records_after_rollout_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert (
        meta[MONITOR_CONTINUATION_PROTOCOL_FIELD]
        == MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1
    )
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    capture = _capture_with_output(monitor_dir, "MUTABLE OUTPUT\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    with override_flags(monitor_continuation_records=False):
        published = persist_monitor_result_best_effort(
            artifacts_dir=monitor_dir,
            meta=meta,
            monitor_state="failed",
            exit_code=1,
            elapsed_seconds=1.5,
            stopped_at=meta["stopped_at"],
            diagnostic_manifest=None,
            retained_log={
                "log_ref": "file:explicit:frozen-log",
                "local_locator": "diagnostics/retained_logs/frozen.log",
                "total_observed_bytes": 17,
                "retained_ranges": [{"start": 0, "end": 17}],
                "complete": True,
                "drain_confirmed": True,
            },
            project_name="proj",
            update_meta=False,
        )
        assert published is not None
        meta["monitor_command"] = "echo MUTABLE COMMAND"

        result = followup_module.launch_followup_agent(
            monitor_dir,
            meta,
            monitor_state="completed",
            exit_code=99,
            elapsed_seconds=999.0,
            capture=capture,
            project_name="proj",
            settle_timeout_seconds=_SETTLE_TIMEOUT,
        )

    assert result.launched is True
    assert captured["extra_env"][MONITOR_CONTINUATION_ENV] == "1"
    delivery_key = json.loads(captured["extra_env"]["SASE_MONITOR_DELIVERY_KEY"])
    assert delivery_key["result_id"] == published.result_id
    assert "| **Outcome** | FAILED — exit 1 |" in captured["prompt"]
    assert "MUTABLE" not in captured["prompt"]


def test_disabled_start_stays_legacy_after_rollout_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with override_flags(monitor_continuation_records=False):
        monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
            tmp_path, monkeypatch
        )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    assert (
        meta[MONITOR_CONTINUATION_PROTOCOL_FIELD]
        == MONITOR_CONTINUATION_PROTOCOL_LEGACY
    )
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    capture = _capture_with_output(monitor_dir, "hello world\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    published = persist_monitor_result_best_effort(
        artifacts_dir=monitor_dir,
        meta=meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        stopped_at=meta["stopped_at"],
        diagnostic_manifest=None,
        retained_log={
            "log_ref": "file:explicit:legacy-log",
            "local_locator": "diagnostics/retained_logs/legacy.log",
            "total_observed_bytes": 12,
            "retained_ranges": [{"start": 0, "end": 12}],
            "complete": True,
            "drain_confirmed": True,
        },
        project_name="proj",
        update_meta=False,
    )
    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.5,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert published is None
    assert result.launched is True
    assert MONITOR_CONTINUATION_ENV not in captured["extra_env"]
    assert "SASE_MONITOR_DELIVERY_KEY" not in captured["extra_env"]
    assert "continuation_monitor_result_id" not in meta
    assert not (Path(monitor_dir) / "continuation" / "delivery").exists()


def test_launch_followup_agent_renders_from_frozen_result_and_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitor_dir, _starter_dir, _project_file = _promote_and_start_monitor(
        tmp_path, monkeypatch
    )
    meta = json.loads((Path(monitor_dir) / "agent_meta.json").read_text())
    meta["stopped_at"] = "2026-08-12T14:19:48+00:00"
    meta["monitor_next_output"] = "none"
    persist_monitor_result(
        artifacts_dir=monitor_dir,
        meta=meta,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=1.5,
        stopped_at=meta["stopped_at"],
        diagnostic_manifest=None,
        retained_log={
            "log_ref": "file:explicit:frozen-log",
            "local_locator": "diagnostics/retained_logs/frozen.log",
            "total_observed_bytes": 17,
            "retained_ranges": [{"start": 0, "end": 17}],
            "complete": True,
            "drain_confirmed": True,
        },
        project_name="proj",
        update_meta=False,
    )
    frozen_result_id = meta["continuation_monitor_result_id"]
    meta["monitor_command"] = "echo MUTABLE COMMAND"
    meta["monitor_cwd"] = "/tmp/mutable-cwd"
    meta["monitor_next_action"] = "MUTABLE NEXT ACTION"
    capture = _capture_with_output(monitor_dir, "MUTABLE OUTPUT\n")
    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = followup_module.launch_followup_agent(
        monitor_dir,
        meta,
        monitor_state="completed",
        exit_code=99,
        elapsed_seconds=999.0,
        capture=capture,
        project_name="proj",
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    prompt = captured["prompt"]
    assert result.launched is True
    assert "| **Outcome** | FAILED — exit 1 |" in prompt
    assert "```text\ntrue\n```" in prompt
    assert str(tmp_path) in prompt
    assert "Report that it finished." in prompt
    assert "MUTABLE" not in prompt
    delivery_key = json.loads(captured["extra_env"]["SASE_MONITOR_DELIVERY_KEY"])
    assert delivery_key["result_id"] == frozen_result_id
