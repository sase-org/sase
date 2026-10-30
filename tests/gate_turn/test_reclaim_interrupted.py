"""Recovery for interrupted gate follow-up launches."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, UTC
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sase.gate_turn._handoff_reconcile as reclaim_mod
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn.handoff import resume_command_for
from sase.gate_turn.reclaim import GateHandoffReconcileSummary
from sase.gate_turn.store import GateTurnSnapshot
from tests.gate_turn._reclaim_helpers import make_reclaim_record


def _started_at_utc(*, age_seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=age_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _interrupted_gate(
    tmp_path: Path,
    *,
    age_seconds: float = 300,
    error_type: str | None = None,
) -> tuple[Path, GateTurnRecord]:
    artifacts_dir = tmp_path / "gate"
    artifacts_dir.mkdir()
    metadata: dict[str, Any] = {
        "cl_name": "question session",
        "gate_id": "question-gate",
        "gate_kind": "question",
        "gate_state": "answered",
        "gate_request_fingerprint": "sha256:request",
        "gate_selected_option_ids": ["submit"],
        "gate_followup_attempt_id": "attempt-1",
        "gate_followup_attempt_stage": "launching",
        "gate_followup_attempt_started_at": _started_at_utc(age_seconds=age_seconds),
        "gate_followup_attempt_live": True,
        "gate_followup_attempt_owner_pid": 999_999,
    }
    if error_type is not None:
        metadata["gate_followup_error_type"] = error_type
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(metadata))
    record = replace(
        make_reclaim_record(
            gate_id="question-gate",
            member_agent_name="question session--gate",
            gate_state="answered",
        ),
        artifacts_dir=str(artifacts_dir),
        project_name="proj",
        kind="question",
        request_fingerprint="sha256:request",
        next_action="resume the question session",
    )
    return artifacts_dir, record


def _pass_state(record: GateTurnRecord) -> SimpleNamespace:
    return SimpleNamespace(
        snapshot=GateTurnSnapshot(
            taken_at=time.time(),
            gate_turns=(record,),
            agent_session_members={},
            record_count=1,
        ),
        project="proj",
        read_seconds=0,
        on_refresh=lambda _gate, _seconds: None,
    )


def _prepare_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
    record: GateTurnRecord,
) -> tuple[list[object], list[dict[str, object]]]:
    submitted: list[object] = []
    notifications: list[dict[str, object]] = []
    evidence = {
        "attached_agent": None,
        "running": False,
        "completed": False,
        "ambiguous": False,
    }

    def classify(*_args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["holds_followup_lock"] is True
        return {
            "needs_attention": True,
            "reason": "stale handoff attempt can be resumed",
            "recovery": "resume",
            "resume_eligible": True,
        }

    def write_meta(
        artifacts_dir: str,
        payload: dict[str, object],
        *,
        index_updater: object = None,
    ) -> None:
        del index_updater
        (Path(artifacts_dir) / "agent_meta.json").write_text(json.dumps(payload))

    monkeypatch.setattr(reclaim_mod, "read_gate_turn_marker", lambda *_args: record)
    monkeypatch.setattr(
        reclaim_mod, "_resolve_agent_session_records", lambda *_args, **_kwargs: ()
    )
    monkeypatch.setattr(
        reclaim_mod, "collect_successor_evidence", lambda **_kwargs: evidence
    )
    monkeypatch.setattr(reclaim_mod, "classify_gate_handoff", classify)
    monkeypatch.setattr(reclaim_mod, "apply_decision", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        reclaim_mod,
        "submit_proc_request",
        lambda request: submitted.append(request),
    )
    monkeypatch.setattr(
        reclaim_mod,
        "notify_handoff_failure",
        lambda meta, **kwargs: notifications.append(
            {
                **meta,
                **kwargs,
                "resume_command": resume_command_for(meta),
            }
        ),
    )
    monkeypatch.setattr("sase.axe.agent_meta.write_agent_meta_atomic", write_meta)
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.update_agent_artifact_index_for_marker_mutation",
        lambda _artifacts_dir: None,
    )
    return submitted, notifications


def _diagnose(record: GateTurnRecord) -> str | None:
    return reclaim_mod._diagnose_one(
        record,
        _pass_state(record),
        deadline=100,
        clock=lambda: 0,
    )


def test_interrupted_attempt_auto_resumes_once_then_notifies_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir, record = _interrupted_gate(tmp_path)
    submitted, notifications = _prepare_diagnosis(monkeypatch, record)

    assert _diagnose(record) == "resumed"

    marker = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert marker["gate_followup_auto_resume_attempt_id"] == "attempt-1"
    assert marker["gate_followup_auto_resume_at"]
    assert len(submitted) == 1
    request = submitted[0]
    assert request.argv == [
        "sase",
        "gate",
        "answer",
        "--id",
        "question-gate",
        "--kind",
        "question",
        "--no-detach",
        "--json",
    ]
    assert request.operation_payload == {
        "option_ids": ["submit"],
        "retry": "resume",
        "source": "gate-reconcile",
    }

    assert _diagnose(record) == "incomplete"
    marker = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert marker["gate_followup_attention_notified_attempt_id"] == "attempt-1"
    assert len(submitted) == 1
    assert len(notifications) == 1
    assert "sase gate answer --kind question --id question-gate" in str(
        notifications[0]["resume_command"]
    )

    assert _diagnose(record) == "incomplete"
    assert len(notifications) == 1
    assert GateHandoffReconcileSummary(resumed=1).to_dict()["handoff_resumed"] == 1


def test_young_interrupted_attempt_defers_without_advancing_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifacts_dir, record = _interrupted_gate(tmp_path, age_seconds=30)
    submitted, notifications = _prepare_diagnosis(monkeypatch, record)
    cursor_writes: list[dict[str, object]] = []
    monkeypatch.setattr(reclaim_mod, "load_reconcile_cursor", lambda _project: {})
    monkeypatch.setattr(
        reclaim_mod,
        "store_reconcile_cursor",
        lambda _project, cursor: cursor_writes.append(dict(cursor)),
    )
    counts = {"scanned": 0}

    deferred = reclaim_mod._reconcile_project(
        "proj",
        [record],
        pass_state=_pass_state(record),
        batch_size=10,
        deadline=10,
        clock=lambda: 0,
        counts=counts,
        error_details=[],
    )

    assert deferred == 1
    assert cursor_writes == []
    assert submitted == []
    assert notifications == []


def test_attempt_with_error_type_is_neither_resumed_nor_renotified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifacts_dir, record = _interrupted_gate(
        tmp_path,
        error_type="RuntimeError",
    )
    submitted, notifications = _prepare_diagnosis(monkeypatch, record)

    assert _diagnose(record) == "incomplete"
    assert submitted == []
    assert notifications == []
