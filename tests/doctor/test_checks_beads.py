"""Tests for Phase 4 doctor bead checks."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_beads import _check_project_beads
from sase.doctor.runner import DoctorContext


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
