"""Tests for doctor bead and agent reconciliation checks."""

from __future__ import annotations

import os
from pathlib import Path

from sase.bead.model import Issue, Status
from sase.bead.stranded import StrandedReport
from sase.bead.stranded_presentation import STRANDED_GLYPH, STRANDED_WORD
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
)
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict
from sase.doctor import checks_beads
from tests.doctor._checks_beads_support import context, stub_agent_scan, stub_issues


def _stub_open_bead(monkeypatch, bead_id: str) -> None:
    """Route the bead reads of ``_check_project_beads`` at one open bead."""
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["OK: no issues found"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.list_issues",
        lambda _path, statuses=None: [
            Issue(
                id=bead_id,
                title="Waiting phase",
                status=Status.OPEN,
                parent_id="sase-1",
            )
        ],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.stats",
        lambda _path: {"open": 1, "claimed": 0, "in_progress": 0, "closed": 0},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        lambda _path: True,
    )


def test_project_beads_resolves_claim_owner_from_any_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    claimed = Issue(
        id="sase-1.1",
        title="Claimed phase",
        status=Status.CLAIMED,
        parent_id="sase-1",
        assignee="waiting-agent",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["OK: no issues found"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.list_issues",
        lambda _path, statuses=None: [claimed],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.stats",
        lambda _path: {"open": 0, "claimed": 1, "in_progress": 0, "closed": 0},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        lambda _path: True,
    )

    def scan(
        root: Path,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        return AgentArtifactScanWire(
            schema_version=4,
            projects_root=str(root),
            options=options,
            stats=AgentArtifactScanStatsWire(),
            records=[
                AgentArtifactRecordWire(
                    project_name="other-project",
                    project_dir=str(root / "other-project"),
                    project_file=str(root / "other-project" / "other-project.sase"),
                    workflow_dir_name="ace-run",
                    artifact_dir=str(root / "other-project" / "artifact"),
                    timestamp="20260724120000",
                    agent_meta=AgentMetaWire(name="waiting-agent", pid=os.getpid()),
                )
            ],
        )

    monkeypatch.setattr("sase.doctor.checks_beads.scan_agent_artifacts", scan)

    check = checks_beads._check_project_beads(context(tmp_path))

    assert check.status == "OK"
    assert check.details == ()


def test_project_beads_warns_about_live_agent_whose_bead_is_unclaimed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The reconciler failing to claim for a live agent is reported, not fixed."""
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    _stub_open_bead(monkeypatch, "sase-1.1")
    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={},
        pid=os.getpid(),
    )

    check = checks_beads._check_project_beads(context(tmp_path))

    assert check.status == "WARN"
    assert "sase-1.1 (sase-1.1)" in check.details[0]
    assert "bead_claim_checks" in check.details[0]
    assert "job is running" in check.details[0]
    assert "chop is running" not in check.details[0]


def test_project_beads_warns_about_claim_whose_owner_died(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A dead claim owner with artifacts present is invisible to every layer."""
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    stub_issues(
        monkeypatch,
        [
            Issue(
                id="sase-1.1",
                title="Claimed phase",
                status=Status.CLAIMED,
                parent_id="sase-1",
                assignee="sase-1.1",
            )
        ],
    )
    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={},
        pid=None,
    )

    check = checks_beads._check_project_beads(context(tmp_path))

    assert check.status == "WARN"
    assert "owning agent is gone" in check.details[0]
    assert "sase-1.1 (sase-1.1)" in check.details[0]


def test_project_beads_does_not_use_the_old_in_progress_gone_warning(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    stub_issues(
        monkeypatch,
        [
            Issue(
                id="sase-1.1",
                title="Running phase",
                status=Status.IN_PROGRESS,
                parent_id="sase-1",
                assignee="sase-1.1",
            )
        ],
    )
    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={"bead_claim_promoted": True},
        pid=None,
    )

    check = checks_beads._check_project_beads(context(tmp_path))

    assert check.status == "OK"
    assert all(
        "in_progress beads whose promoted agent is gone" not in message
        for message in check.details
    )


def test_project_beads_warns_about_stranded_beads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    stub_issues(
        monkeypatch,
        [
            Issue(
                id="sase-1.2",
                title="Stranded phase",
                status=Status.IN_PROGRESS,
                parent_id="sase-1",
                assignee="sase-1.2",
            )
        ],
    )
    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.2",
        bead_id="sase-1.2",
        agent_meta={},
        pid=None,
    )
    now = 1_700_000_000.0
    loaded = StrandedReport(
        report=StrandedWorkReport(
            schema_version=1,
            verdicts=(
                StrandedWorkVerdict(
                    bead_id="sase-1.2",
                    kind="phase",
                    state="stranded",
                    reason="kept",
                    session="sase-1.2",
                    last_turn="sase-1.2",
                    since=now - 23 * 3600,
                ),
            ),
            stranded_ids=("sase-1.2",),
        ),
        titles={"sase-1.2": "Stranded phase"},
        generated_at=now,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.load_stranded_report",
        lambda _project, now=None: loaded,
    )

    check = checks_beads._check_project_beads(context(tmp_path, project="demo"))

    assert check.status == "WARN"
    detail = check.details[0]
    assert f"{STRANDED_GLYPH} {STRANDED_WORD}" in detail
    assert "sase-1.2" in detail
    assert "ended with bead_action keep; nothing resumes it" in detail
    assert "23h" in detail
    assert "%id(bead=sase-1.2) #fork:sase-1.2" in detail
    assert 'sase bead close sase-1.2 --note "…"' in detail


def test_project_beads_stays_silent_for_a_live_in_progress_owner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    stub_issues(
        monkeypatch,
        [
            Issue(
                id="sase-1.1",
                title="Running phase",
                status=Status.IN_PROGRESS,
                parent_id="sase-1",
                assignee="sase-1.1",
            )
        ],
    )
    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={"bead_claim_promoted": True},
        pid=os.getpid(),
    )

    assert checks_beads._check_project_beads(context(tmp_path)).status == "OK"


def test_project_beads_ignores_promoted_and_dead_bead_owners(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    _stub_open_bead(monkeypatch, "sase-1.1")
    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={"bead_claim_promoted": True},
        pid=os.getpid(),
    )

    assert checks_beads._check_project_beads(context(tmp_path)).status == "OK"

    stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={},
        pid=None,
    )

    assert checks_beads._check_project_beads(context(tmp_path)).status == "OK"
