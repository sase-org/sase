"""Collector coverage for open completion-failure recovery candidates."""

from __future__ import annotations

import os
import json
from pathlib import Path

from sase.bead.model import BeadCompletionFailure, Status
from sase.bead.stranded_facts import collect_stranded_work_input
from sase.core.agent_scan_wire import DoneMarkerWire
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    epic,
    phase,
    record,
    task,
    wire_collector,
)

_NOW = 1_700_000_000.0
_PID = os.getpid()
_FAILED_AT = "2023-11-14T22:11:20+00:00"


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def _failure(*, agent_name: str = "origin-agent") -> BeadCompletionFailure:
    return BeadCompletionFailure(
        close_event_id="beads-1:close-event",
        run_id="origin-run",
        agent_name=agent_name,
        artifact_dir="/artifacts/origin-run",
        failed_at=_FAILED_AT,
        failure_code="hook_failed",
        evidence_locations=("/artifacts/origin-run/failure.json",),
    )


def test_unassigned_recovery_candidate_loads_failure_run(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "origin-run")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            task(
                "sase-yo",
                status=Status.OPEN,
                completion_failure=_failure(),
            )
        ],
        [
            record(
                artifact,
                name="origin-agent",
                session="origin-session",
                done=DoneMarkerWire(outcome="failed", finished_at=_NOW - 3600),
            )
        ],
    )
    bead = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-yo")
    assert bead["candidate"] is True
    assert bead["status"] == "open"
    assert bead["assignee"] is None
    assert bead["completion_failure"]["run_id"] == "origin-run"
    assert bead["completion_failure"]["agent_name"] == "origin-agent"
    assert bead["members"][0]["name"] == "origin-agent"
    assert bead["members"][0]["lifecycle"] == "failed"


def test_terminal_workspace_retention_marks_member_as_stranded_owner(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "origin-run")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            phase(
                "sase-yo",
                status=Status.OPEN,
                completion_failure=_failure(),
            )
        ],
        [
            record(
                artifact,
                name="origin-agent",
                session="origin-session",
                done=DoneMarkerWire(outcome="failed", finished_at=_NOW - 3600),
            )
        ],
    )
    retention_path = artifact / "diagnostics" / "workspace_retention.json"
    retention_path.parent.mkdir()
    retention_path.write_text(
        json.dumps(
            {
                "kind": "terminal_workspace_retention",
                "disposition": "retain",
                "workspace_num": 17,
                "settled_at": None,
            }
        ),
        encoding="utf-8",
    )

    facts = collect_stranded_work_input(PROJECT, now=_NOW)
    member = bead_facts(facts, "sase-yo")["members"][0]
    assert member["workspace_retention"] is True

    retention = json.loads(retention_path.read_text(encoding="utf-8"))
    retention["settled_at"] = "2026-01-01T00:00:00+00:00"
    retention_path.write_text(json.dumps(retention), encoding="utf-8")
    facts = collect_stranded_work_input(PROJECT, now=_NOW)
    member = bead_facts(facts, "sase-yo")["members"][0]
    assert member["workspace_retention"] is False


def test_historical_settled_boolean_does_not_clear_stranded_projection(
    monkeypatch, tmp_path: Path
) -> None:
    from sase.workspace_provider.retention_record import (
        mark_workspace_retention_settled,
        read_workspace_retention_record,
    )

    artifact = _dir(tmp_path, "origin-run")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            phase(
                "sase-yo",
                status=Status.OPEN,
                completion_failure=_failure(),
            )
        ],
        [
            record(
                artifact,
                name="origin-agent",
                session="origin-session",
                done=DoneMarkerWire(outcome="failed", finished_at=_NOW - 3600),
            )
        ],
    )
    retention_path = artifact / "diagnostics" / "workspace_retention.json"
    retention_path.parent.mkdir()
    retention_path.write_text(
        json.dumps(
            {
                "kind": "terminal_workspace_retention",
                "disposition": "retain",
                "workspace_num": 17,
                "settled": True,
            }
        ),
        encoding="utf-8",
    )

    typed = read_workspace_retention_record(artifact)
    assert typed is not None and typed.unresolved is True
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-yo")[
        "members"
    ][0]
    assert member["workspace_retention"] is True

    assert mark_workspace_retention_settled(
        artifact, reason="resume_transfer", settled_at="2026-01-01T00:00:00+00:00"
    )
    typed = read_workspace_retention_record(artifact)
    assert typed is not None and typed.unresolved is False
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-yo")[
        "members"
    ][0]
    assert member["workspace_retention"] is False


def test_ordinary_open_draft_is_not_a_candidate(monkeypatch, tmp_path: Path) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-draft", status=Status.OPEN)],
        [],
    )
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    assert all(item["id"] != "sase-draft" for item in payload["beads"])


def test_closed_and_canceled_beads_stay_out_of_candidates(
    monkeypatch, tmp_path: Path
) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            phase("sase-closed", status=Status.CLOSED, assignee="sase-closed"),
            phase(
                "sase-recovered",
                status=Status.OPEN,
                completion_failure=_failure(),
            ),
        ],
        [],
    )
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    ids = [item["id"] for item in payload["beads"]]
    assert "sase-recovered" in ids
    assert "sase-closed" not in ids


def test_failure_run_is_queried_once_when_shared(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "origin-run")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            phase(
                "sase-1.2",
                status=Status.OPEN,
                completion_failure=_failure(),
            ),
            task(
                "sase-9",
                status=Status.OPEN,
                completion_failure=_failure(),
            ),
        ],
        [
            record(
                artifact,
                name="origin-agent",
                session="origin-session",
                done=DoneMarkerWire(outcome="failed", finished_at=_NOW - 3600),
            )
        ],
    )
    from sase.bead import stranded_facts as facts

    calls: list[list[str]] = []
    original = facts._query_session_records_chunk

    def wrapped(project: str, keys: list[str]) -> object:
        calls.append(list(keys))
        return original(project, keys)

    monkeypatch.setattr(facts, "_query_session_records_chunk", wrapped)
    collect_stranded_work_input(PROJECT, now=_NOW)
    assert calls == [["origin-agent"]]


def test_distinct_assignee_and_failure_agent_are_both_loaded(
    monkeypatch, tmp_path: Path
) -> None:
    successor = _dir(tmp_path, "successor")
    origin = _dir(tmp_path, "origin-run")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            phase(
                "sase-1.2",
                assignee="successor",
                status=Status.IN_PROGRESS,
                completion_failure=_failure(),
            )
        ],
        [
            record(successor, name="successor", session="successor", pid=_PID),
            record(
                origin,
                name="origin-agent",
                session="origin-session",
                done=DoneMarkerWire(outcome="failed", finished_at=_NOW - 3600),
            ),
        ],
    )
    from sase.bead import stranded_facts as facts

    calls: list[list[str]] = []
    original = facts._query_session_records_chunk

    def wrapped(project: str, keys: list[str]) -> object:
        calls.append(list(keys))
        return original(project, keys)

    monkeypatch.setattr(facts, "_query_session_records_chunk", wrapped)
    bead = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")
    assert calls == [["origin-agent", "successor"]]
    names = {member["name"] for member in bead["members"]}
    assert names == {"successor", "origin-agent"}
    assert bead["assignee"] == "successor"


def test_in_progress_parent_stays_a_candidate_beside_recovered_child(
    monkeypatch, tmp_path: Path
) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            epic("sase-1", assignee="sase-1.land"),
            phase(
                "sase-1.2",
                status=Status.OPEN,
                parent_id="sase-1",
                completion_failure=_failure(),
            ),
        ],
        [],
    )
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    parent = bead_facts(payload, "sase-1")
    child = bead_facts(payload, "sase-1.2")
    assert parent["candidate"] is True
    assert parent["status"] == "in_progress"
    assert parent["completion_failure"] is None
    assert child["candidate"] is True
    assert child["status"] == "open"
    assert child["parent_id"] == "sase-1"
