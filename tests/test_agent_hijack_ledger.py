"""Exclusive create, CAS, torn-write, and settled-move tests for the hijack ledger."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack.ledger import (
    HijackLedgerConflict,
    cas_advance_record,
    create_record,
    list_active_records,
    load_record,
    load_record_by_agent_name,
    load_record_by_artifacts_dir,
    load_record_by_workspace,
    mark_stopping_if_requested,
    new_requested_record,
)


def _advance(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    updated = dict(record)
    name = event.get("event")
    if name == "begin_stop":
        updated["state"] = "stopping"
    elif name == "stop_failed":
        updated["state"] = "stop_failed"
        updated["error"] = event.get("error")
    elif name == "confirmed_stop":
        updated["state"] = "held"
    else:
        raise AssertionError(f"unexpected event {name!r}")
    updated["revision"] = int(record["revision"]) + 1
    updated["updated_at"] = event.get("at")
    return updated


@pytest.fixture
def hijack_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setattr(
        "sase.agent.hijack.ledger.agent_hijack_wire_schema_version",
        lambda: 1,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.ledger.advance_agent_hijack_record",
        _advance,
    )
    return home


def _requested(artifacts: Path, hijack_id: str = "h-1") -> dict[str, Any]:
    return new_requested_record(
        hijack_id=hijack_id,
        agent_name="agent.1",
        artifacts_dir=str(artifacts),
        project_file="/tmp/project.sase",
        workspace_num=4,
        pid=123,
    )


def test_exclusive_create_rejects_a_second_writer(
    hijack_home: Path, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    first = create_record(_requested(artifacts))
    assert first["state"] == "requested"
    with pytest.raises(FileExistsError):
        create_record(_requested(artifacts))
    loaded = load_record("h-1")
    assert loaded is not None
    assert loaded["revision"] == 0


def test_cas_concurrent_begin_stop_has_exactly_one_winner(
    hijack_home: Path, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    record = create_record(_requested(artifacts))
    barrier = threading.Barrier(2)
    winners: list[dict[str, Any]] = []
    conflicts: list[HijackLedgerConflict] = []

    def worker() -> None:
        barrier.wait()
        try:
            winners.append(cas_advance_record(record, {"event": "begin_stop"}))
        except HijackLedgerConflict as exc:
            conflicts.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(winners) == 1
    assert len(conflicts) == 1
    loaded = load_record("h-1")
    assert loaded is not None
    assert loaded["state"] == "stopping"
    assert loaded["revision"] == 1


def test_load_skips_torn_json(hijack_home: Path, tmp_path: Path) -> None:
    from sase.agent.hijack.ledger import _hijack_record_path

    path = _hijack_record_path("torn")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    assert load_record("torn") is None


def test_atomic_replace_leaves_valid_json(hijack_home: Path, tmp_path: Path) -> None:
    from sase.agent.hijack.ledger import _hijack_record_path

    artifacts = tmp_path / "artifacts"
    record = create_record(_requested(artifacts))
    cas_advance_record(record, {"event": "begin_stop"})
    payload = json.loads(_hijack_record_path("h-1").read_text(encoding="utf-8"))
    assert payload["state"] == "stopping"
    assert payload["revision"] == 1


def test_terminal_state_moves_to_settled(hijack_home: Path, tmp_path: Path) -> None:
    from sase.agent.hijack.ledger import _hijack_record_path

    artifacts = tmp_path / "artifacts"
    record = create_record(_requested(artifacts))
    stopping = cas_advance_record(record, {"event": "begin_stop"})
    failed = cas_advance_record(stopping, {"event": "stop_failed", "error": "alive"})
    assert failed["state"] == "stop_failed"
    assert not _hijack_record_path("h-1").exists()
    settled = _hijack_record_path("h-1", settled=True)
    assert settled.is_file()
    assert list_active_records() == []
    loaded = load_record("h-1")
    assert loaded is not None
    assert loaded["state"] == "stop_failed"


def test_lookups_by_artifacts_name_and_workspace(
    hijack_home: Path, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    create_record(_requested(artifacts))
    assert load_record_by_artifacts_dir(str(artifacts))["hijack_id"] == "h-1"
    assert load_record_by_agent_name("agent.1")["hijack_id"] == "h-1"
    assert load_record_by_workspace("/tmp/project.sase", 4)["hijack_id"] == "h-1"


def test_mark_stopping_if_requested_is_idempotent(
    hijack_home: Path, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    create_record(_requested(artifacts))
    first = mark_stopping_if_requested(str(artifacts))
    second = mark_stopping_if_requested(str(artifacts))
    assert first is not None
    assert first["state"] == "stopping"
    assert second is not None
    assert second["state"] == "stopping"
    assert second["revision"] == 1
