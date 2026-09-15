"""Proc wire round-trip, legacy-payload compatibility, and proc-id tests."""

from __future__ import annotations

from sase.procs import (
    STORE_LOG_OWNER,
    TUI_PROC_KIND,
    Proc,
    ProcAppendOutcome,
    ProcPruneOutcome,
    ProcStoreSnapshot,
    ProcUpdate,
    ProcUpdateOutcome,
    new_proc_id,
    short_proc_id,
)
from sase.procs.ids import PROC_ID_ALPHABET, PROC_ID_LENGTH

from tests._procs_facade_helpers import _proc


def test_proc_wire_round_trip_ignores_unknown_fields() -> None:
    proc = _proc("0123456789ab")
    payload = proc.to_dict()
    payload["future_field"] = {"new": True}

    restored = Proc.from_dict(payload)

    assert restored == proc
    assert restored.to_dict()["project"] == "sase"


def test_legacy_task_wire_payloads_parse_as_proc_models() -> None:
    proc = _proc("0123456789ab")
    task_payload = proc.to_dict()
    task_payload["task_id"] = task_payload.pop("proc_id")
    snapshot_payload = {
        "schema_version": 1,
        "tasks": [task_payload],
        "stats": {},
    }

    snapshot = ProcStoreSnapshot.from_dict(snapshot_payload)
    appended = ProcAppendOutcome.from_dict(
        {
            "schema_version": 1,
            "snapshot": snapshot_payload,
            "pruned_task_ids": ["old-task"],
        }
    )
    updated = ProcUpdateOutcome.from_dict(
        {
            "schema_version": 1,
            "task": task_payload,
            "matched": True,
        }
    )
    pruned = ProcPruneOutcome.from_dict(
        {
            "schema_version": 1,
            "snapshot": snapshot_payload,
            "pruned_task_ids": ["old-task"],
        }
    )

    assert snapshot.procs == [proc]
    assert appended.pruned_proc_ids == ["old-task"]
    assert updated.proc == proc
    assert pruned.pruned_proc_ids == ["old-task"]


def test_legacy_commandless_tui_payload_receives_proc_shell_defaults() -> None:
    snapshot = ProcStoreSnapshot.from_dict(
        {
            "schema_version": 2,
            "procs": [
                {
                    "proc_id": "legacy-tui",
                    "label": "Legacy TUI",
                    "kind": TUI_PROC_KIND,
                    "status": "running",
                    "command": [],
                    "cwd": "/tmp",
                    "origin": "test",
                    "created_at": "2026-07-25T12:00:00Z",
                    "log_path": "/tmp/legacy-tui.log",
                }
            ],
            "stats": {},
        }
    )

    proc = snapshot.procs[0]
    assert proc.schema_version == 2
    assert proc.argv == []
    assert proc.log_owner == STORE_LOG_OWNER
    assert proc.lifecycle == "legacy"


def test_proc_update_distinguishes_omitted_from_explicit_null() -> None:
    update = ProcUpdate(proc_id="0123456789ab", phase=None, pid=42)

    assert update.to_dict() == {
        "proc_id": "0123456789ab",
        "pid": 42,
        "phase": None,
    }
    assert ProcUpdate.from_dict(
        {"proc_id": "0123456789ab", "phase": None, "future": "ignored"}
    ).to_dict() == {"proc_id": "0123456789ab", "phase": None}


def test_proc_id_generation_and_short_form() -> None:
    ids = {new_proc_id() for _ in range(100)}

    assert len(ids) == 100
    assert all(len(proc_id) == PROC_ID_LENGTH for proc_id in ids)
    assert all(set(proc_id) <= set(PROC_ID_ALPHABET) for proc_id in ids)
    assert short_proc_id("0123456789ab") == "012345"
