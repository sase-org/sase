"""Tests for project bead checks in doctor."""

from __future__ import annotations

from pathlib import Path

from sase.bead.model import Issue, Status
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)
from sase.doctor import checks_beads
from tests.doctor._checks_beads_support import context
from tests.sdd_policy_helpers import set_sdd_policy


def test_project_beads_skips_when_store_is_absent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Isolate the resolver itself: the upward walk from tmp_path would
    # otherwise find the host's live bead store and return OK.
    monkeypatch.setattr(
        "sase.doctor.checks_beads._find_existing_beads_dir",
        lambda _context: None,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.resolve_current_project_record",
        lambda _context: None,
    )

    check = checks_beads._check_project_beads(context(tmp_path))

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

    check = checks_beads._check_project_beads(context(tmp_path))

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

    check = checks_beads._check_project_beads(context(tmp_path))

    assert check.status == "OK"
    assert check.data["beads_dir"] == str(local_beads)


def test_project_beads_discovers_split_sidecar(monkeypatch, tmp_path: Path) -> None:
    beads_dir = tmp_path / "sase" / "repos" / "beads"
    beads_dir.mkdir(parents=True)
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
        lambda _path: {"open": 0, "claimed": 0, "in_progress": 0, "closed": 0},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_beads.bead_state_is_clean",
        lambda _path: True,
    )

    check = checks_beads._check_project_beads(context(tmp_path))

    assert check.status == "OK"
    assert check.data["beads_dir"] == str(beads_dir)


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

    check = checks_beads._check_project_beads(context(tmp_path))

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

    check = checks_beads._check_project_beads(context(tmp_path))

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

    check = checks_beads._check_project_beads(context(tmp_path))

    assert check.status == "WARN"
    assert "sase-1.1" in check.details[0]
    assert "sase bead open <id>" in check.details[0]
