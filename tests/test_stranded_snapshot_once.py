"""Facts and titles share one stranded snapshot (bead sase-1t3.11.1.5)."""

from __future__ import annotations

from typing import Any

import sase.bead.stranded as stranded_module
from sase.bead import stranded_facts as facts
from sase.bead.model import BeadTier, Issue, IssueType, Status
from tests._stranded_collector_helpers import PROJECT, bead_facts

_NOW = 1_700_000_000.0


def _phase(bead_id: str, **extra: Any) -> Issue:
    return Issue(
        id=bead_id,
        title=f"Title {bead_id}",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PHASE,
        parent_id="s.epic",
        **extra,
    )


def _epic(bead_id: str) -> Issue:
    return Issue(
        id=bead_id,
        title=f"Title {bead_id}",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )


def _child(bead_id: str, parent_id: str) -> Issue:
    return Issue(
        id=bead_id,
        title=f"Title {bead_id}",
        status=Status.CLOSED,
        issue_type=IssueType.PLAN,
        tier=BeadTier.PLAN,
        parent_id=parent_id,
    )


def _install(monkeypatch: Any, tmp_path: Any, issues: list[Issue]) -> dict[str, int]:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir(exist_ok=True)
    calls = {"snapshots": 0}

    def stranded_snapshot(
        _beads_dir: Any, bead_ids: Any = None
    ) -> tuple[list[Issue], list[Issue]]:
        calls["snapshots"] += 1
        return [issue for issue in issues if issue.status is Status.IN_PROGRESS], [
            issue for issue in issues if issue.status is Status.CLOSED
        ]

    monkeypatch.setattr(facts, "stranded_snapshot", stranded_snapshot)
    monkeypatch.setattr(facts, "canonical_beads_dir_for_project", lambda _p: beads_dir)
    monkeypatch.setattr(facts, "_session_record_cache", lambda _p, _k: {})
    return calls


def test_facts_and_titles_share_one_snapshot(monkeypatch: Any, tmp_path: Any) -> None:
    """The combined collector runs one snapshot for facts and titles."""
    calls = _install(
        monkeypatch, tmp_path, [_phase("s.1"), _epic("s.epic"), _child("s.c", "s.1")]
    )

    payload, titles = facts.collect_stranded_work_snapshot(PROJECT, now=_NOW)

    assert calls["snapshots"] == 1
    fact_ids = {bead["id"] for bead in payload["beads"]}
    assert fact_ids == {"s.1", "s.epic", "s.c"}
    assert set(titles) == fact_ids
    assert titles["s.1"] == "Title s.1"
    assert bead_facts(payload, "s.1")["candidate"] is True
    assert bead_facts(payload, "s.c")["candidate"] is False


def test_single_collectors_still_agree_with_combined(
    monkeypatch: Any, tmp_path: Any
) -> None:
    """The legacy single collectors match the combined snapshot output."""
    issues = [_phase("s.1"), _epic("s.epic"), _child("s.c", "s.1")]
    _install(monkeypatch, tmp_path, issues)

    payload, titles = facts.collect_stranded_work_snapshot(PROJECT, now=_NOW)

    assert facts.collect_stranded_work_input(PROJECT, now=_NOW) == payload
    assert facts.collect_issue_titles(PROJECT) == titles


def test_report_titles_cover_facts_from_one_snapshot(
    monkeypatch: Any, tmp_path: Any
) -> None:
    """load_stranded_report collects once and keeps titles coherent."""
    calls = _install(
        monkeypatch, tmp_path, [_phase("s.1"), _epic("s.epic"), _child("s.c", "s.1")]
    )

    report = stranded_module.load_stranded_report(PROJECT, now=_NOW)

    assert calls["snapshots"] == 1
    assert set(report.titles) == {"s.1", "s.epic", "s.c"}
    assert {verdict.bead_id for verdict in report.report.verdicts} <= set(report.titles)
    assert report.generated_at == _NOW
