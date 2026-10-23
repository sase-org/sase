"""One collector fixture per active ACE status."""

from __future__ import annotations

import os
from pathlib import Path

from sase.bead.stranded_facts import collect_stranded_work_input
from sase.core.agent_scan_wire import PendingQuestionMarkerWire, WaitingMarkerWire
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    phase,
    record,
    wire_collector,
)

_NOW = 1_700_000_000.0
_PID = os.getpid()


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def test_starting_without_pid_is_not_process_live(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "starting")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [record(artifact, name="sase-1.2", session="sase-1.2")],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["lifecycle"] == "starting"
    assert member["process_live"] is False


def test_running_with_pid_is_process_live(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "running")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                pid=_PID,
                run_started_at="2026-10-22T12:00:00-04:00",
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["lifecycle"] == "running"
    assert member["process_live"] is True


def test_waiting_without_pid_is_process_live(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "waiting")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                waiting=WaitingMarkerWire(waiting_for=["sase-9"]),
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["lifecycle"] == "waiting"
    assert member["process_live"] is True


def test_queued_without_pid_is_process_live(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "queued")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                waiting=WaitingMarkerWire(
                    slot_requested_at="2026-10-22T12:00:00-04:00"
                ),
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["lifecycle"] == "queued"
    assert member["process_live"] is True


def test_question_without_pid_is_process_live(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "question")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                pending_question=PendingQuestionMarkerWire(session_id="q1"),
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["lifecycle"] == "asking"
    assert member["process_live"] is True


def test_finalizing_sets_the_finalizing_flag(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "finalizing")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                pid=_PID,
                run_started_at="2026-10-22T12:00:00-04:00",
                finalizer_phase="executing",
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["finalizing"] is True
    assert member["lifecycle"] == "running"
    assert member["process_live"] is True
