"""Deterministic stranded Beads inventory shared by unit and PNG tests."""

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.tui.models import agent_stranded
from sase.bead.model import Status
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict
from tests.ace.tui._artifacts_beads_helpers import snapshot

NOW = 1783512000.0


def stranded_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    value = snapshot(tmp_path)
    for item in (*value.tasks, *value.epics, *value.phases_by_epic["alpha", "alpha-1"]):
        item.issue.status = Status.IN_PROGRESS
    value = replace(value, triage_gates={}, plan_links={})
    verdicts = (
        StrandedWorkVerdict("alpha-1", "epic", "blocked", blocked_by=("alpha-1.2",)),
        StrandedWorkVerdict("alpha-1.1", "phase", "blocked", blocked_by=("alpha-1.2",)),
        StrandedWorkVerdict(
            "alpha-1.2",
            "phase",
            "stranded",
            reason="kept",
            since=NOW - 3600,
            parent_id="alpha-1",
            last_turn="alpha-1.2--3",
            blocks=("alpha-1",),
        ),
        StrandedWorkVerdict(
            "alpha-open",
            "task",
            "stranded",
            reason="failed",
            since=NOW - 7200,
            last_turn="alpha-open--1",
        ),
    )
    report = StrandedReport(
        report=StrandedWorkReport(
            verdicts=verdicts,
            stranded_ids=("alpha-1.2", "alpha-open"),
            blocked_ids=("alpha-1", "alpha-1.1"),
        ),
        titles={},
        generated_at=NOW,
    )
    cache = agent_stranded._StrandedReportCache(max_entries=8)
    monkeypatch.setattr(agent_stranded, "_STRANDED_REPORT_CACHE", cache)
    cache.set("alpha", report, "fixture")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_stranded.time", lambda: NOW
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_detail_properties.time", lambda: NOW
    )
    return value, report
