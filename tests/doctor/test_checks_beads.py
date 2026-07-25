"""Tests for Phase 4 doctor bead checks."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sase.bead.model import Issue, Status
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
)
from sase.doctor.checks_beads import _check_project_beads
from sase.doctor.runner import DoctorContext
from tests.sdd_policy_helpers import set_sdd_policy


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def test_project_beads_skips_when_store_is_absent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_beads.resolve_current_project_record",
        lambda _context: None,
    )

    check = _check_project_beads(_context(tmp_path))

    assert check.status == "SKIP"
    assert "no bead store" in check.summary


def test_project_beads_adapts_warning_messages(monkeypatch, tmp_path: Path) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["WARNING: issues.jsonl missing"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.stats",
        lambda _path: {"open": 1, "in_progress": 0, "closed": 0},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        lambda _path: True,
    )

    check = _check_project_beads(_context(tmp_path))

    assert check.status == "WARN"
    assert "1 warning" in check.summary
    assert check.details == ("WARNING: issues.jsonl missing",)
    assert check.data["beads_dir"] == str(beads_dir)


def test_project_beads_prefers_resolved_local_store(
    monkeypatch, tmp_path: Path
) -> None:
    in_tree_beads = tmp_path / "sdd" / "beads"
    local_beads = tmp_path / ".sase" / "sdd" / "beads"
    in_tree_beads.mkdir(parents=True)
    local_beads.mkdir(parents=True)
    set_sdd_policy(monkeypatch, "local")
    monkeypatch.setattr(
        "sase.doctor.checks_beads.resolve_current_project_record",
        lambda _context: None,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["OK: no issues found"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.stats",
        lambda _path: {"open": 1, "in_progress": 0, "closed": 0},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        lambda _path: True,
    )

    check = _check_project_beads(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["beads_dir"] == str(local_beads)


def test_project_beads_summary_counts_claimed_issues(
    monkeypatch, tmp_path: Path
) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["OK: bead store healthy"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.stats",
        lambda _path: {
            "open": 1,
            "claimed": 2,
            "in_progress": 3,
            "closed": 4,
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        lambda _path: True,
    )

    check = _check_project_beads(_context(tmp_path))

    assert check.status == "OK"
    assert check.summary == "bead store healthy; 10 issue(s)"


def test_project_beads_degrades_when_git_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A missing git binary must degrade the sync probe, not crash doctor."""
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["OK: no issues found"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.stats",
        lambda _path: {"open": 1, "in_progress": 0, "closed": 0},
    )

    def _raise(_path: Path) -> bool:
        raise FileNotFoundError("git")

    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        _raise,
    )

    check = _check_project_beads(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["sync_clean"] is None


def test_project_beads_warns_about_claim_without_resolvable_artifact(
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
        assignee="missing-agent",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["OK: no issues found"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.list_issues",
        lambda _path, statuses: [claimed],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.stats",
        lambda _path: {"open": 0, "claimed": 1, "in_progress": 0, "closed": 0},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        lambda _path: True,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.scan_agent_artifacts",
        lambda _root, options: AgentArtifactScanWire(
            schema_version=4,
            projects_root=str(tmp_path / ".sase" / "projects"),
            options=options,
            stats=AgentArtifactScanStatsWire(),
            records=[],
        ),
    )

    check = _check_project_beads(_context(tmp_path))

    assert check.status == "WARN"
    assert "sase-1.1" in check.details[0]
    assert "sase bead open <id>" in check.details[0]


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
        lambda _path, statuses: [claimed],
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
                    agent_meta=AgentMetaWire(name="waiting-agent"),
                )
            ],
        )

    monkeypatch.setattr("sase.doctor.checks_beads.scan_agent_artifacts", scan)

    check = _check_project_beads(_context(tmp_path))

    assert check.status == "OK"
    assert check.details == ()


def _stub_open_bead(monkeypatch, bead_id: str) -> None:
    """Route the bead reads of ``_check_project_beads`` at one open bead."""
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.doctor",
        lambda _path: ["OK: no issues found"],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.rust_beads.list_issues",
        lambda _path, statuses: [
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


def _stub_agent_scan(
    monkeypatch,
    tmp_path: Path,
    *,
    agent_name: str,
    bead_id: str,
    agent_meta: dict[str, object],
    pid: int | None,
) -> None:
    """Publish one ace-run artifact record backed by a real metadata file."""
    artifact_dir = tmp_path / "artifacts" / agent_name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"name": agent_name, "bead_id": bead_id, **agent_meta}),
        encoding="utf-8",
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
                    project_name="proj",
                    project_dir=str(root / "proj"),
                    project_file=str(root / "proj" / "proj.sase"),
                    workflow_dir_name="ace-run",
                    artifact_dir=str(artifact_dir),
                    timestamp="20260725120000",
                    agent_meta=AgentMetaWire(
                        name=agent_name,
                        bead_id=bead_id,
                        pid=pid,
                    ),
                )
            ],
        )

    monkeypatch.setattr("sase.doctor.checks_beads.scan_agent_artifacts", scan)


def test_project_beads_warns_about_live_agent_whose_bead_is_unclaimed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The reconciler failing to claim for a live agent is reported, not fixed."""
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    _stub_open_bead(monkeypatch, "sase-1.1")
    _stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={},
        pid=os.getpid(),
    )

    check = _check_project_beads(_context(tmp_path))

    assert check.status == "WARN"
    assert "sase-1.1 (sase-1.1)" in check.details[0]
    assert "bead_claim_checks" in check.details[0]


def test_project_beads_ignores_promoted_and_dead_bead_owners(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "sdd" / "beads").mkdir(parents=True)
    _stub_open_bead(monkeypatch, "sase-1.1")
    _stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={"bead_claim_promoted": True},
        pid=os.getpid(),
    )

    assert _check_project_beads(_context(tmp_path)).status == "OK"

    _stub_agent_scan(
        monkeypatch,
        tmp_path,
        agent_name="sase-1.1",
        bead_id="sase-1.1",
        agent_meta={},
        pid=None,
    )

    assert _check_project_beads(_context(tmp_path)).status == "OK"
