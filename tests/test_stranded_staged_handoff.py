"""Staged-handoff ownership coverage for the stranded-work collector.

Proves the staged fields ride the pinned Rust reducer: a valid staged plan
record, a held receipt, and malformed staged state all own the bead through
``handoff``, while a lone ``adopted`` receipt does not.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    build_plan_staged_record,
    write_adoption_receipt,
)
from sase.bead.stranded import load_stranded_report
from sase.bead.stranded_facts import collect_stranded_work_input
from sase.core.agent_scan_wire import DoneMarkerWire
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    phase,
    record,
    wire_collector,
)

_NOW = 1_700_000_000.0
_STAGED_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def _write_plan_record(artifact: Path) -> None:
    payload = build_plan_staged_record(
        plan_file=str(artifact / "plan.md"),
        original_file=str(artifact / "scratch.md"),
        dirty_obligations_at_stage=[],
        staged_id=_STAGED_ID,
    )
    (artifact / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_receipt(artifact: Path, outcome: str, reason: str | None = None) -> None:
    receipt: dict[str, object] = {
        "staged_id": _STAGED_ID,
        "adopted_at": "2026-10-28T12:02:00Z",
        "outcome": outcome,
    }
    if reason is not None:
        receipt["reason"] = reason
    write_adoption_receipt(receipt, artifacts_dir=str(artifact))  # type: ignore[arg-type]


def _done_records(artifact: Path):
    return [
        record(
            artifact,
            name="sase-1.2",
            session="sase-1.2",
            done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 5),
        )
    ]


def _verdict(tmp_path: Path):
    report = load_stranded_report(PROJECT, now=_NOW)
    return next(item for item in report.report.verdicts if item.bead_id == "sase-1.2")


def test_valid_staged_plan_record_is_owned_through_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_plan_record(artifact)
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_handoff"] == "plan"
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned"
    assert verdict.reason == "handoff"


def test_held_receipt_alone_is_owned_through_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_receipt(artifact, "handoff_not_adopted", reason="no finalizer settlement")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_receipt_outcome"] == "handoff_not_adopted"
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned"
    assert verdict.reason == "handoff"


def test_malformed_staged_record_is_owned_through_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    (artifact / STAGED_HANDOFF_FILENAME).write_text("{}", encoding="utf-8")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_handoff"] == "malformed"
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned"
    assert verdict.reason == "handoff"


def test_adopted_receipt_alone_is_not_owned_through_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_receipt(artifact, "adopted")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_receipt_outcome"] == "adopted"
    verdict = _verdict(tmp_path)
    assert not (verdict.state == "owned" and verdict.reason == "handoff")
