"""Operational soak for epic_resume_gate against real artifacts and gates."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.axe.run_agent_runner_finalize import write_error_done_marker
from sase.bead.epic_resume_launch import build_epic_resume_argv
from sase.feature_flags import current_flags, override_flags
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV, apply_feature_flags_env
from sase.xprompt.workflow_models import WorkflowExecutionError

from tests._epic_resume_soak_helpers import (
    FAILED_TS,
    GENERATION,
    LIVE_GENERATION,
    LIVE_TS,
    PROJECT,
    WAITING_TS,
    init_stalled_epic,
    iso_seconds_ago,
    load_epic_resume_requests,
    plant_member,
    plant_settled_stall,
    run_chop,
    seed_project_spec,
    write_json,
)
from tests.fakey.harness import FakeyRetryHarness, _launch_timestamp


def test_historical_failed_phase_without_done_finished_at_raises_one_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_home: Path,
) -> None:
    del gate_home
    beads_dir, epic_id, failed_id, waiting_id = init_stalled_epic(tmp_path)
    plant_settled_stall(
        epic_id=epic_id,
        failed_bead_id=failed_id,
        waiting_bead_id=waiting_id,
    )

    first = run_chop(tmp_path, monkeypatch, beads_dir)
    second = run_chop(tmp_path, monkeypatch, beads_dir)

    requests = load_epic_resume_requests()
    assert first.counters["gated"] == 1
    assert first.counters["stalled"] == 1
    assert second.counters["skipped"] == 1
    assert len(requests) == 1
    request = requests[0]
    payload = request["payload"]
    assert request["kind"] == "epic_resume"
    assert payload["project"] == PROJECT
    assert payload["epic_id"] == epic_id
    assert payload["clan_generation"] == GENERATION
    assert payload["resume_argv"] == build_epic_resume_argv(epic_id)
    assert payload["failed_members"][0]["agent_name"] == f"{epic_id}.1"
    assert payload["failed_members"][0]["bead_id"] == failed_id
    assert payload["waiting_members"][0]["agent_name"] == f"{epic_id}.2"
    assert payload["remaining_phase_count"] == 2
    assert "Resume stalled epic" in request["presentation"]["title"]
    preview = (_kind_dir() / request["request_id"] / "epic.md").read_text(
        encoding="utf-8"
    )
    assert f"# Resume stalled epic {epic_id}" in preview
    assert "sase bead work" in preview
    assert epic_id in preview


def test_fast_retry_and_live_handoff_do_not_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_home: Path,
) -> None:
    del gate_home
    beads_dir, epic_id, failed_id, waiting_id = init_stalled_epic(tmp_path)
    plant_settled_stall(
        epic_id=epic_id,
        failed_bead_id=failed_id,
        waiting_bead_id=waiting_id,
        age_seconds=30,
    )

    recent = run_chop(tmp_path, monkeypatch, beads_dir)
    assert recent.reason == "no_stall_changes"
    assert load_epic_resume_requests() == []

    plant_member(
        timestamp=LIVE_TS,
        name=f"{epic_id}.land",
        bead_id=f"{epic_id}.land",
        epic_id=epic_id,
        generation=LIVE_GENERATION,
        pid=os.getpid(),
    )
    handoff = run_chop(tmp_path, monkeypatch, beads_dir)
    assert handoff.reason == "no_stall_changes"
    assert load_epic_resume_requests() == []


def test_recovery_before_settle_never_creates_a_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_home: Path,
) -> None:
    del gate_home
    beads_dir, epic_id, failed_id, waiting_id = init_stalled_epic(tmp_path)
    seed_project_spec()
    plant_member(
        timestamp=FAILED_TS,
        name=f"{epic_id}.1",
        bead_id=failed_id,
        epic_id=epic_id,
        outcome="failed",
        stopped_at=iso_seconds_ago(30),
    )
    plant_member(
        timestamp=WAITING_TS,
        name=f"{epic_id}.2",
        bead_id=waiting_id,
        epic_id=epic_id,
    )

    unsettled = run_chop(tmp_path, monkeypatch, beads_dir)
    plant_member(
        timestamp=LIVE_TS,
        name=f"{epic_id}.land",
        bead_id=f"{epic_id}.land",
        epic_id=epic_id,
        generation=LIVE_GENERATION,
        pid=os.getpid(),
    )
    recovered = run_chop(tmp_path, monkeypatch, beads_dir)

    assert unsettled.reason == "no_stall_changes"
    assert recovered.reason == "no_stall_changes"
    assert load_epic_resume_requests() == []


def test_live_resume_cancels_the_pending_production_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_home: Path,
) -> None:
    del gate_home
    beads_dir, epic_id, failed_id, waiting_id = init_stalled_epic(tmp_path)
    plant_settled_stall(
        epic_id=epic_id,
        failed_bead_id=failed_id,
        waiting_bead_id=waiting_id,
    )
    gated = run_chop(tmp_path, monkeypatch, beads_dir)
    assert gated.counters["gated"] == 1
    request_id = gated_request_id()
    assert (_kind_dir() / request_id / "request.json").is_file()

    plant_member(
        timestamp=LIVE_TS,
        name=f"{epic_id}.land",
        bead_id=f"{epic_id}.land",
        epic_id=epic_id,
        generation=LIVE_GENERATION,
        pid=os.getpid(),
    )
    canceled = run_chop(tmp_path, monkeypatch, beads_dir)

    assert canceled.counters["canceled"] == 1
    assert (_kind_dir() / request_id / "cancellation.json").is_file()


def test_flag_off_creates_no_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_home: Path,
) -> None:
    del gate_home
    beads_dir, epic_id, failed_id, waiting_id = init_stalled_epic(tmp_path)
    plant_settled_stall(
        epic_id=epic_id,
        failed_bead_id=failed_id,
        waiting_bead_id=waiting_id,
    )

    result = run_chop(tmp_path, monkeypatch, beads_dir, flag_enabled=False)

    assert result.reason == "flag_disabled"
    assert load_epic_resume_requests() == []


def test_fakey_failed_phase_gates_after_settle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_home: Path,
) -> None:
    del gate_home
    beads_dir, epic_id, failed_id, waiting_id = init_stalled_epic(tmp_path)
    seed_project_spec()
    artifact_dir = _fail_phase_with_fakey(
        tmp_path / "fakey",
        monkeypatch,
        epic_id=epic_id,
        failed_bead_id=failed_id,
    )
    done = json.loads((artifact_dir / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "failed"
    assert isinstance(done["finished_at"], float)
    plant_member(
        timestamp=WAITING_TS,
        name=f"{epic_id}.2",
        bead_id=waiting_id,
        epic_id=epic_id,
    )

    result = run_chop(tmp_path, monkeypatch, beads_dir, settle_seconds=0)
    requests = load_epic_resume_requests()

    assert result.counters["gated"] == 1
    assert len(requests) == 1
    assert requests[0]["payload"]["failed_members"][0]["agent_name"] == f"{epic_id}.1"
    assert requests[0]["payload"]["resume_argv"] == build_epic_resume_argv(epic_id)


def test_axe_child_env_inherits_enabled_epic_resume_gate() -> None:
    with override_flags(epic_resume_gate=True):
        env: dict[str, str] = {}
        apply_feature_flags_env(current_flags(), env)
        payload = json.loads(env[SASE_FEATURE_FLAGS_ENV])

    assert payload["epic_resume_gate"] is True


def _fail_phase_with_fakey(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    epic_id: str,
    failed_bead_id: str,
) -> Path:
    harness = FakeyRetryHarness(tmp_path, monkeypatch, max_retries=0)
    harness.use_scenario(
        monkeypatch,
        [
            {
                "fail": {
                    "message": "phase crashed",
                    "retryable": False,
                    "exit_code": 1,
                    "channel": "stderr",
                }
            }
        ],
    )
    error = "phase crashed"
    try:
        result = harness.run("Fail this epic phase.")
    except WorkflowExecutionError as exc:
        error = str(exc)
    else:
        assert result.success is False
    if not (harness.artifacts / "done.json").is_file():
        write_error_done_marker(
            current_artifacts_dir=str(harness.artifacts),
            cl_name=PROJECT,
            project_file=str(harness.project_file),
            timestamp=_launch_timestamp(harness.artifacts_timestamp),
            artifacts_timestamp=harness.artifacts_timestamp,
            workspace_num=1,
            workspace_dir=str(harness.workspace),
            output_path=str(harness.root / "output.log"),
            agent_name=f"{epic_id}.1",
            agent_model="fakey-large",
            agent_llm_provider="fakey",
            agent_vcs_provider=None,
            agent_hidden=False,
            error=error,
            traceback_str=error,
        )
    planted = plant_member(
        timestamp=FAILED_TS,
        name=f"{epic_id}.1",
        bead_id=failed_bead_id,
        epic_id=epic_id,
        outcome="failed",
        stopped_at=iso_seconds_ago(0),
    )
    done = json.loads((harness.artifacts / "done.json").read_text(encoding="utf-8"))
    done["name"] = f"{epic_id}.1"
    write_json(planted / "done.json", done)
    meta = json.loads((planted / "agent_meta.json").read_text(encoding="utf-8"))
    meta["stopped_at"] = iso_seconds_ago(0)
    write_json(planted / "agent_meta.json", meta)
    return planted


def _kind_dir() -> Path:
    from sase.notification_gates.paths import interaction_requests_dir

    return interaction_requests_dir() / "epic_resume"


def gated_request_id() -> str:
    requests = load_epic_resume_requests()
    assert requests
    request_id = requests[0]["request_id"]
    assert isinstance(request_id, str)
    return request_id
