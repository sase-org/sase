"""Tests for held staged-handoff notes on runner completion notifications."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_runner_finalize import (
    _held_staged_handoff_note,
    send_completion_notification,
)

pytest_plugins = ("tests._run_agent_runner_notification_fixtures",)


def test_held_staged_handoff_note_names_exact_readopt_command(tmp_path, monkeypatch):
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "review--plan"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_adoption_receipt",
        lambda _path: {
            "outcome": "handoff_not_adopted",
            "staged_id": "stage-1",
            "reason": "finalizer settlement is incomplete",
        },
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_staged_handoff",
        lambda _path: {"kind": "pipe", "staged_id": "stage-1"},
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_staged_handoff_response",
        lambda _staged_id, **_kwargs: "persisted response",
    )

    note = _held_staged_handoff_note(str(tmp_path))

    assert note is not None
    assert "Staged pipe handoff stage-1" in note
    assert "review--plan" in note
    assert "sase agent readopt review--plan" in note
    assert "finalizer settlement is incomplete" in note


def test_held_staged_handoff_without_recovery_evidence_prompts_salvage(
    tmp_path, monkeypatch
):
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "review--plan"}), encoding="utf-8"
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_adoption_receipt",
        lambda _path: {
            "outcome": "handoff_not_adopted",
            "staged_id": "stage-1",
            "reason": "staged monitor member is unknown",
        },
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.read_staged_handoff",
        lambda _path: {
            "kind": "monitor",
            "staged_id": "stage-1",
            "payload": {"monitor_id": "monitor-1"},
        },
    )

    note = _held_staged_handoff_note(str(tmp_path))

    assert note is not None
    assert "salvage the workspace's work" in note.lower()
    assert "dismiss this agent" in note.lower()
    assert "sase agent readopt" not in note


def _write_staged_plan_record(base_kwargs, *, staged_id: str) -> None:
    from sase.agent.staged_handoff import (
        STAGED_HANDOFF_FILENAME,
        build_plan_staged_record,
    )

    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    record = build_plan_staged_record(
        plan_file=str(artifacts_dir / "plan.md"),
        original_file=str(artifacts_dir / "scratch.md"),
        dirty_obligations_at_stage=[],
        staged_id=staged_id,
    )
    (artifacts_dir / STAGED_HANDOFF_FILENAME).write_text(json.dumps(record))


def _write_held_receipt(base_kwargs, *, staged_id: str, reason: str) -> None:
    from sase.agent.staged_handoff import write_adoption_receipt

    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "handoff_not_adopted",
            "reason": reason,
        },
        artifacts_dir=base_kwargs["current_artifacts_dir"],
    )


def test_failed_notification_names_held_staged_handoff(base_kwargs):
    staged_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    reason = "finalizer controller did not settle successfully"
    base_kwargs["success"] = False
    _write_staged_plan_record(base_kwargs, staged_id=staged_id)
    _write_held_receipt(base_kwargs, staged_id=staged_id, reason=reason)

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    notes = mock_notify.call_args.kwargs["notes"]
    assert any(
        "plan" in note
        and staged_id in note
        and reason in note
        and "was not adopted" in note
        for note in notes
    )


def test_adopted_receipt_produces_no_held_note(base_kwargs):
    from sase.agent.staged_handoff import write_adoption_receipt

    staged_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    base_kwargs["success"] = False
    _write_staged_plan_record(base_kwargs, staged_id=staged_id)
    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "adopted",
        },
        artifacts_dir=base_kwargs["current_artifacts_dir"],
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    notes = mock_notify.call_args.kwargs["notes"]
    assert not any("was not adopted" in note for note in notes)
    assert not any("malformed" in note for note in notes)


def test_no_staged_files_produces_no_held_note(base_kwargs):
    base_kwargs["success"] = False

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    notes = mock_notify.call_args.kwargs["notes"]
    assert not any("was not adopted" in note for note in notes)
    assert not any("malformed" in note for note in notes)


def test_malformed_receipt_produces_malformed_held_note(base_kwargs):
    from sase.agent.staged_handoff import STAGED_HANDOFF_RECEIPT_FILENAME

    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / STAGED_HANDOFF_RECEIPT_FILENAME).write_text(
        "{not-json", encoding="utf-8"
    )
    base_kwargs["success"] = False

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_count == 1
    notes = mock_notify.call_args.kwargs["notes"]
    assert any("malformed" in note and "held" in note for note in notes)
