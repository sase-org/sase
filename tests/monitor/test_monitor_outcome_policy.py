"""Frozen outcome-policy start fingerprints and settlement."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.continuation_capture import persist_frozen_outcome_policy
from sase.core.continuation_facade import freeze_continuation_policy
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.monitor.followup import FollowupLaunchResult
from sase.monitor.models import MonitorError
from sase.monitor.outcome_policy import settlement_policy_decision
from sase.monitor.output import OutputCapture
from sase.monitor.request import StartMonitorRequest, monitor_request_fingerprint
from sase.monitor.settlement import settle_claim_and_followup
from sase.monitor.start import start_monitor
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, patch_project_records, write_project_file


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _policy(*, completed: str = "none", failed_next: str = "repair") -> dict[str, Any]:
    return {
        "completed": {"action": completed, "next_action": None}
        if completed == "none"
        else {
            "action": "continue",
            "next_action": "from policy",
            "model": "@small",
        },
        "failed": {
            "action": "continue",
            "next_action": failed_next,
            "model": "opus@high",
        },
        "timeout": {"action": "none"},
    }


def _freeze(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "explicit_policy": _policy(),
        "shared_next": "shared follow-up",
    }
    payload.update(overrides)
    return freeze_continuation_policy(payload)


def test_changed_policy_file_changes_the_start_fingerprint() -> None:
    shared = {"lane": "acme", "label": "true"}
    first = monitor_request_fingerprint(
        StartMonitorRequest(
            command="true",
            reason="verify",
            timeout_seconds=30.0,
            cwd="/tmp",
            project_name="proj",
            start_status="TESTING",
            stop_status="TESTED",
            next_action="shared follow-up",
            policy_digest=_freeze()["fingerprint"],
        ),
        **shared,
    )
    second = monitor_request_fingerprint(
        StartMonitorRequest(
            command="true",
            reason="verify",
            timeout_seconds=30.0,
            cwd="/tmp",
            project_name="proj",
            start_status="TESTING",
            stop_status="TESTED",
            next_action="shared follow-up",
            policy_digest=_freeze(explicit_policy=_policy(completed="continue"))[
                "fingerprint"
            ],
        ),
        **shared,
    )
    assert first != second
    assert first.startswith("sha256:")


def test_start_rejects_complete_without_prepared_intent_before_creating_a_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_project_file("proj")
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        agent_family="acme",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    with pytest.raises(MonitorError, match="prepared completion"):
        start_monitor(
            StartMonitorRequest(
                command="true",
                reason="verify",
                timeout_seconds=30.0,
                cwd=str(tmp_path),
                project_name="proj",
                start_status="TESTING",
                stop_status="TESTED",
                lane="acme",
                inherit_lane_workspace_claim=False,
                outcome_policy={
                    "completed": {"action": "complete"},
                    "failed": {"action": "none"},
                    "timeout": {"action": "none"},
                },
            )
        )
    artifacts_root = Path(starter_dir).parents[2]
    members = [
        path.parent
        for path in artifacts_root.glob("*/*/*/agent_meta.json")
        if path.parent != Path(starter_dir)
    ]
    assert members == []


def _make_settlement_monitor(tmp_path: Path, **meta: object) -> str:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-monitor", "acme", pid=os.getpid())],
    )
    return make_starter_agent(
        "proj",
        "20260912120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="abc123def456",
        monitor_command="true",
        monitor_cwd=str(tmp_path),
        monitor_reason="test",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_timeout_seconds=30.0,
        monitor_next_action="shared follow-up",
        monitor_state="running",
        cl_name="acme",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        shell_kind="proc",
        **meta,
    )


def test_settlement_executes_frozen_none_despite_shared_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = _make_settlement_monitor(tmp_path)
    persist_frozen_outcome_policy(artifacts_dir, _freeze())
    launches: list[str | None] = []

    def fake_launch(
        _artifacts_dir: str, meta: dict[str, Any], **_kwargs: object
    ) -> FollowupLaunchResult:
        launches.append(str(meta.get("monitor_next_action") or "") or None)
        return FollowupLaunchResult(launched=True, agent_name="acme--1")

    settle_claim_and_followup(
        artifacts_dir,
        json.loads((Path(artifacts_dir) / "agent_meta.json").read_text()),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=fake_launch,
    )
    assert launches == []

    settle_claim_and_followup(
        artifacts_dir,
        json.loads((Path(artifacts_dir) / "agent_meta.json").read_text()),
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=1.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=fake_launch,
    )
    assert launches == ["repair"]


def test_settlement_does_not_dispatch_stopped_or_lost_even_when_policy_continues(
    tmp_path: Path,
) -> None:
    artifacts_dir = _make_settlement_monitor(tmp_path)
    persist_frozen_outcome_policy(
        artifacts_dir,
        _freeze(
            explicit_policy={
                "completed": {"action": "continue", "next_action": "keep going"},
                "failed": {"action": "continue", "next_action": "keep going"},
                "timeout": {"action": "continue", "next_action": "keep going"},
                "stopped": {"action": "continue", "next_action": "stopped next"},
                "lost": {"action": "continue", "next_action": "lost next"},
            }
        ),
    )
    launches: list[str] = []

    def fake_launch(
        _artifacts_dir: str, _meta: dict[str, Any], **_kwargs: object
    ) -> FollowupLaunchResult:
        launches.append("launched")
        return FollowupLaunchResult(launched=True, agent_name="acme--1")

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    settle_claim_and_followup(
        artifacts_dir,
        dict(meta),
        monitor_state="stopped",
        exit_code=130,
        elapsed_seconds=1.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=fake_launch,
    )
    settle_claim_and_followup(
        artifacts_dir,
        dict(meta),
        monitor_state="lost",
        exit_code=None,
        elapsed_seconds=1.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=fake_launch,
    )
    assert launches == []


def test_legacy_records_decode_missing_evidence_as_tail(tmp_path: Path) -> None:
    artifacts_dir = _make_settlement_monitor(tmp_path)
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    meta.pop("monitor_next_output", None)
    decision = settlement_policy_decision(artifacts_dir, meta, "completed")
    assert decision["action"] == "continue"
    assert decision["evidence_policy"] == "tail"
    assert "legacy_record" in decision["reasons"]
