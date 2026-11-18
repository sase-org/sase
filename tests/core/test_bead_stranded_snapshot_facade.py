"""Facade tests for the slim stranded-work snapshot (bead sase-1t3.11.1.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.bead.model import Issue
from sase.core import bead_read_facade as facade

_FAILURE: dict[str, Any] = {
    "close_event_id": "evt-1",
    "run_id": "run-1",
    "agent_name": "sase-x",
    "artifact_dir": "/tmp/x",
    "failed_at": "2026-01-02T00:00:00Z",
    "failure_code": "failed",
}


def _row(
    bead_id: str,
    title: str,
    status: str,
    issue_type: str,
    created_at: str,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": bead_id,
        "title": title,
        "status": status,
        "issue_type": issue_type,
        "created_at": created_at,
        "updated_at": created_at,
    }
    row.update(extra)
    return row


def _seed_store(beads_dir: Path, *, history: int = 0) -> None:
    beads_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        _row(
            "s.epic",
            "Epic",
            "in_progress",
            "plan",
            "2026-01-01T00:00:03Z",
            tier="epic",
            description="heavy description that must not cross",
            design="heavy design that must not cross",
            notes=[
                {
                    "id": "n1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "author": "a",
                    "text": "heavy note",
                }
            ],
            refs=["research:202607/report.md"],
            links=[
                {
                    "target_ref": "bead:s.ph1",
                    "relation": "related",
                    "description": "heavy link",
                    "origin": "manual",
                }
            ],
        ),
        _row(
            "s.ph1",
            "Phase",
            "in_progress",
            "phase",
            "2026-01-01T00:00:01Z",
            parent_id="s.epic",
            assignee="s.ph1",
        ),
        _row(
            "s.ph2",
            "Phase with failure",
            "open",
            "phase",
            "2026-01-01T00:00:02Z",
            parent_id="s.epic",
            completion_failure=dict(_FAILURE),
        ),
        _row(
            "s.backlog",
            "Backlog",
            "open",
            "phase",
            "2026-01-01T00:00:04Z",
            parent_id="s.epic",
        ),
        _row(
            "s.ctx1",
            "Child",
            "closed",
            "plan",
            "2026-01-01T00:00:05Z",
            tier="plan",
            parent_id="s.ph1",
        ),
        _row(
            "s.shut",
            "Shut",
            "closed",
            "phase",
            "2026-01-01T00:00:06Z",
            parent_id="s.epic",
        ),
    ]
    for seq in range(history):
        rows.append(
            _row(
                f"s.hist{seq}",
                f"History {seq}",
                "closed",
                "task",
                "2026-01-01T01:00:00Z",
                description="history ballast " * 40,
            )
        )
    (beads_dir / "issues.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def _key(issue: Issue) -> tuple[Any, ...]:
    failure = issue.completion_failure
    return (
        issue.id,
        issue.title,
        issue.status,
        issue.issue_type,
        issue.tier,
        issue.parent_id,
        issue.assignee,
        issue.closed_at,
        None
        if failure is None
        else (
            failure.close_event_id,
            failure.run_id,
            failure.agent_name,
            failure.artifact_dir,
            failure.failed_at,
            failure.failure_code,
        ),
    )


def _binding_snapshot(
    beads_dir: Path, bead_ids: list[str] | None = None
) -> tuple[list[Issue], list[Issue]]:
    binding = facade.optional_rust_binding("bead_stranded_snapshot")
    assert binding is not None, "the test core must expose the snapshot binding"
    payload = binding(str(beads_dir), bead_ids)
    from sase.core.bead_wire import issues_from_list

    return (
        issues_from_list(list(payload["candidates"])),
        issues_from_list(list(payload["context"])),
    )


def test_snapshot_binding_matches_fallback(tmp_path: Path) -> None:
    """The slim binding and the legacy two-query path select the same rows."""
    beads_dir = tmp_path / "beads"
    _seed_store(beads_dir, history=50)

    binding_candidates, binding_context = _binding_snapshot(beads_dir)
    fallback_candidates, fallback_context = facade._stranded_snapshot_fallback(
        beads_dir
    )

    assert [_key(issue) for issue in binding_candidates] == [
        _key(issue) for issue in fallback_candidates
    ]
    assert [_key(issue) for issue in binding_context] == [
        _key(issue) for issue in fallback_context
    ]
    assert [issue.id for issue in binding_candidates] == [
        "s.ph1",
        "s.ph2",
        "s.epic",
    ]
    assert [issue.id for issue in binding_context] == ["s.ctx1"]

    scoped_binding, scoped_context = _binding_snapshot(beads_dir, ["s.ph1"])
    scoped_fallback, scoped_fallback_context = facade._stranded_snapshot_fallback(
        beads_dir, bead_ids=["s.ph1"]
    )
    assert (
        [issue.id for issue in scoped_binding]
        == [issue.id for issue in scoped_fallback]
        == ["s.ph1"]
    )
    assert [issue.id for issue in scoped_context] == [
        issue.id for issue in scoped_fallback_context
    ]


def test_snapshot_projection_drops_heavy_fields(tmp_path: Path) -> None:
    """Slim rows carry no descriptions, notes, links, refs, or designs."""
    beads_dir = tmp_path / "beads"
    _seed_store(beads_dir)

    candidates, context = _binding_snapshot(beads_dir)

    epic = next(issue for issue in candidates if issue.id == "s.epic")
    assert epic.description == ""
    assert epic.design == ""
    assert epic.notes == []
    assert epic.links == []
    assert epic.refs == []
    assert epic.title == "Epic"

    fallback_candidates, _ = facade._stranded_snapshot_fallback(beads_dir)
    heavy = next(issue for issue in fallback_candidates if issue.id == "s.epic")
    assert heavy.description != ""
    assert heavy.notes != []

    assert {issue.id for issue in candidates} == {"s.ph1", "s.ph2", "s.epic"}
    assert [issue.id for issue in context] == ["s.ctx1"]


def test_snapshot_scales_with_candidates_not_history(tmp_path: Path) -> None:
    """Two thousand closed beads add no Python issue materialization."""
    beads_dir = tmp_path / "beads"
    _seed_store(beads_dir, history=2000)

    candidates, context = facade.stranded_snapshot(beads_dir)

    assert [issue.id for issue in candidates] == ["s.ph1", "s.ph2", "s.epic"]
    assert [issue.id for issue in context] == ["s.ctx1"]
