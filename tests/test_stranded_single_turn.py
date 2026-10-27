"""Single-turn session coverage for the stranded-work collector.

A session's root member keeps ``agent_meta.agent_session`` null until it gets
a successor. The collector must still see it through the ``agent_name``
candidate filter, so a one-turn phase that ended without closing its bead is
classified ``stranded``/``unclosed`` instead of ``unknown``/``no_records``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.bead.stranded import load_stranded_report
from sase.bead import stranded_facts as facts
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    DoneMarkerWire,
    WaitingMarkerWire,
)
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    epic,
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


def _capturing_collector(
    monkeypatch: Any,
    tmp_path: Path,
    issues: list[Any],
    records: list[AgentArtifactRecordWire],
) -> list[Any]:
    """Like ``wire_collector`` but captures the index queries sent."""
    captured: list[Any] = []
    wire_collector(monkeypatch, tmp_path, issues, records)
    original = facts.query_agent_artifact_index

    def query(
        index_path: Path,
        projects_root: Path,
        index_query: Any,
        options: AgentArtifactScanOptionsWire | None,
    ) -> AgentArtifactScanWire:
        captured.append(index_query)
        return original(index_path, projects_root, index_query, options)

    monkeypatch.setattr(facts, "query_agent_artifact_index", query)
    return captured


def _root_done_records(tmp_path: Path) -> list[AgentArtifactRecordWire]:
    artifact = _dir(tmp_path, "sase-1.2")
    return [
        record(
            artifact,
            name="sase-1.2",
            session=None,
            done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 3600),
        )
    ]


def test_single_turn_query_matches_session_or_name(monkeypatch, tmp_path: Path) -> None:
    captured = _capturing_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _root_done_records(tmp_path),
    )
    bead = bead_facts(facts.collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")
    assert bead["records_available"] is True
    assert len(bead["members"]) == 1
    assert bead["members"][0]["name"] == "sase-1.2"
    assert len(captured) == 1
    candidate_filter = captured[0].candidate_filter
    assert candidate_filter == {
        "kind": "any",
        "filters": [
            {"kind": "equals", "field": "agent_session", "value": "sase-1.2"},
            {"kind": "equals", "field": "agent_name", "value": "sase-1.2"},
        ],
    }


def test_single_turn_unclosed_phase_is_stranded(monkeypatch, tmp_path: Path) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _root_done_records(tmp_path),
    )
    report = load_stranded_report(PROJECT, now=_NOW)
    assert report.report.stranded_ids == ("sase-1.2",)
    verdict = next(
        item for item in report.report.verdicts if item.bead_id == "sase-1.2"
    )
    assert verdict.state == "stranded"
    assert verdict.reason == "unclosed"


def test_single_turn_stranded_phase_blocks_parent_epic(
    monkeypatch, tmp_path: Path
) -> None:
    land_dir = _dir(tmp_path, "sase-1.land")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            epic("sase-1", assignee="sase-1.land"),
            phase("sase-1.2", assignee="sase-1.2", parent_id="sase-1"),
        ],
        [
            *_root_done_records(tmp_path),
            # The land agent is a live single-turn waiter: a root member
            # with no agent_session, owned until propagation marks it
            # blocked on the stranded leaf.
            record(
                land_dir,
                name="sase-1.land",
                session=None,
                run_started_at="2026-10-22T12:00:00-04:00",
                waiting=WaitingMarkerWire(waiting_for=["sase-1.2"]),
            ),
        ],
    )
    report = load_stranded_report(PROJECT, now=_NOW)
    assert report.report.stranded_ids == ("sase-1.2",)
    assert "sase-1" in report.report.blocked_ids
    parent = next(item for item in report.report.verdicts if item.bead_id == "sase-1")
    assert parent.state == "blocked"
    assert "sase-1.2" in parent.blocked_by


def test_live_single_turn_waiting_member_is_owned(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session=None,
                run_started_at="2026-10-22T12:00:00-04:00",
                waiting=WaitingMarkerWire(waiting_for=["sase-9"]),
            )
        ],
    )
    report = load_stranded_report(PROJECT, now=_NOW)
    verdict = next(
        item for item in report.report.verdicts if item.bead_id == "sase-1.2"
    )
    assert verdict.state == "owned"


def test_duplicate_artifact_dirs_are_deduped(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session=None,
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 3600),
            ),
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 3600),
            ),
        ],
    )
    bead = bead_facts(facts.collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")
    assert len(bead["members"]) == 1


def test_multi_member_session_classifies_as_before(monkeypatch, tmp_path: Path) -> None:
    root_dir = _dir(tmp_path, "root")
    successor_dir = _dir(tmp_path, "successor")
    records = [
        record(
            root_dir,
            name="sase-1.2",
            session=None,
            done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 3600),
        ),
        record(
            successor_dir,
            name="sase-1.2--plan",
            session="sase-1.2",
            done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 3600),
        ),
    ]
    wire_collector(
        monkeypatch, tmp_path, [phase("sase-1.2", assignee="sase-1.2")], records
    )
    multi = load_stranded_report(PROJECT, now=_NOW)
    multi_verdict = next(
        item for item in multi.report.verdicts if item.bead_id == "sase-1.2"
    )

    wire_collector(
        monkeypatch, tmp_path, [phase("sase-1.2", assignee="sase-1.2")], records[1:]
    )
    single = load_stranded_report(PROJECT, now=_NOW)
    single_verdict = next(
        item for item in single.report.verdicts if item.bead_id == "sase-1.2"
    )

    assert multi_verdict.state == single_verdict.state == "stranded"
    assert multi_verdict.reason == single_verdict.reason == "unclosed"
