"""Durable typed-admission behavior for keep-work recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack.recovery_admission import (
    RECOVERY_ADMISSION_METADATA_KEY,
    RECOVERY_ADMISSION_SOURCE_SURFACE,
    cancel_recovery_admission_request,
    observe_recovery_admission,
)
from sase.agent.launch_admission import (
    cancel_typed_launch_request,
    dispatch_typed_launch_request,
    run_coordinator_in_bundle,
)
from sase.agent.launch_admission_store import admission_dir, append_journal
from sase.agent.launch_request_planning import prepare_typed_launch_plan
from sase.agent.launch_request_response import REQUEST_FILENAME
from sase.core.agent_launch_facade import dispatch_fingerprint
from sase.core.agent_launch_wire import launch_plan_from_dict
from sase.core.atomic_json import write_json_marker_atomic


def test_cancelled_waiting_recovery_request_stays_cancelled_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import ledger
    from sase.core import paths

    state_root = tmp_path / ".sase"
    monkeypatch.setattr(paths, "sase_subdir", lambda name: state_root / name)
    request_id = "hijack-recover-h-123-cancelled"
    bundle = state_root / "typed_launches" / request_id
    bundle.mkdir(parents=True)
    plan_data = prepare_typed_launch_plan(
        "%id(acme--4)\n%model:claude/opus@high\n%wait(time=1h)\nRecovery prompt",
        selected_project="proj",
        launch_kind="multi_prompt",
    )
    plan = launch_plan_from_dict(plan_data)
    unit = plan.units[0]
    fingerprint = dispatch_fingerprint(
        plan.content_digest, unit.logical_id, unit.payload
    )
    descriptor = {
        "schema_version": 1,
        "hijack_id": "h-123",
        "action": "continue",
        "target": "claude/opus@high",
        "reserved_successor_name": "acme--4",
        "project_name": "proj",
        "project_file": str(tmp_path / "proj.sase"),
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "expected_claim_owner_pid": 111,
        "launch_identity": "launch-123",
        "admission_request_id": request_id,
        "dispatch_fingerprint": fingerprint,
        "logical_id": unit.logical_id,
    }
    data: dict[str, Any] = {
        "request_id": request_id,
        "source_surface": RECOVERY_ADMISSION_SOURCE_SURFACE,
        "typed_plan": plan_data,
        "plan_digest": plan.content_digest,
        "plan_schema_version": plan.schema_version,
        "dispatch": {"cwd": str(tmp_path), "prompt": "Recovery prompt"},
        "launch_submitted_at": "2026-11-05T00:00:00Z",
        "selected_project": "proj",
        "safe_inputs": {},
        "unit_dispatch_metadata": {
            RECOVERY_ADMISSION_METADATA_KEY: descriptor,
        },
    }
    write_json_marker_atomic(
        bundle / REQUEST_FILENAME,
        {"kind": "direct_typed_launch", "request_id": request_id, "payload": data},
    )

    record = {
        "state": "resolving",
        "hijack_id": "h-123",
        "resolution_action": "continue",
        "reserved_successor_name": "acme--4",
        "concrete_target_model": "claude/opus@high",
        "launch_identity": "launch-123",
        "admission_request_id": request_id,
        "admission_identity": fingerprint,
        "workspace_num": 3,
        "workspace_dir": "/ws/3",
        "project_file": descriptor["project_file"],
        "expected_claim_owner_pid": 111,
    }
    monkeypatch.setattr(ledger, "load_record", lambda _hijack_id: dict(record))

    def cas_advance(current: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        assert current["state"] == "resolving"
        assert event["event"] == "resolution_failed"
        record["state"] = "held"
        record["error"] = event["error"]
        return dict(record)

    monkeypatch.setattr(ledger, "cas_advance_record", cas_advance)
    dispatches: list[str] = []
    first = dispatch_typed_launch_request(
        bundle,
        data,
        agent_dispatcher=lambda *_args: (
            dispatches.append("spawn") or (True, "x", None, [])
        ),
        spawn_coordinator=False,
    )
    assert first.admission_complete is False
    assert dispatches == []
    assert observe_recovery_admission(request_id)["state"] == "waiting"

    cancelled = cancel_recovery_admission_request(request_id, reason="stop request")
    assert cancelled["state"] == "cancelled"
    assert cancelled["recovery_state"] == "held"
    assert record["state"] == "held"

    # A fresh coordinator reads the same bundle and cancellation marker. It
    # cannot invoke the reconstructed recovery dispatcher after cancellation.
    progress = run_coordinator_in_bundle(bundle)
    assert progress.complete is True
    journal = (bundle / "launch_admission" / "journal.jsonl").read_text()
    assert json.loads(journal.splitlines()[-1])["phase"] == "cancelled"
    assert dispatches == []
    status = observe_recovery_admission(request_id)
    assert status["state"] == "cancelled"
    assert status["cancel_requested"] is True


def test_cancellation_keeps_an_uncertain_dispatch_nonterminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core import paths
    from sase.core.agent_launch_wire import LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION

    state_root = tmp_path / ".sase"
    monkeypatch.setattr(paths, "sase_subdir", lambda name: state_root / name)
    request_id = "hijack-recover-h-123-dispatching"
    bundle = state_root / "typed_launches" / request_id
    bundle.mkdir(parents=True)
    plan_data = prepare_typed_launch_plan(
        "%id(acme--4)\n%model:claude/opus@high\nRecovery prompt",
        selected_project="proj",
        launch_kind="multi_prompt",
    )
    plan = launch_plan_from_dict(plan_data)
    unit = plan.units[0]
    fingerprint = dispatch_fingerprint(
        plan.content_digest, unit.logical_id, unit.payload
    )
    data: dict[str, Any] = {
        "request_id": request_id,
        "source_surface": RECOVERY_ADMISSION_SOURCE_SURFACE,
        "typed_plan": plan_data,
        "plan_digest": plan.content_digest,
        "dispatch": {"cwd": str(tmp_path), "prompt": "Recovery prompt"},
        "unit_dispatch_metadata": {
            RECOVERY_ADMISSION_METADATA_KEY: {
                "logical_id": unit.logical_id,
                "dispatch_fingerprint": fingerprint,
            }
        },
    }
    write_json_marker_atomic(
        bundle / REQUEST_FILENAME,
        {"kind": "direct_typed_launch", "request_id": request_id, "payload": data},
    )
    append_journal(
        admission_dir(bundle),
        {
            "schema_version": LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
            "seq": 1,
            "logical_id": unit.logical_id,
            "phase": "dispatching",
            "recorded_at_unix": 1.0,
            "fingerprint": fingerprint,
        },
    )

    result = cancel_typed_launch_request(bundle, reason="stop uncertain attempt")
    assert result["state"] == "dispatching"
    assert result["admission_complete"] is False
    restarted = run_coordinator_in_bundle(bundle)
    assert restarted.complete is False
    assert observe_recovery_admission(request_id)["state"] == "dispatching"
