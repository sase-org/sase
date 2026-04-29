"""Tests for refresh_deltas_for_changespec and the sync-deltas CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sase.ace.changespec import DeltaEntry
from sase.ace.deltas import refresh_deltas_for_changespec


def _write_project(tmp_path: Path, body: str) -> Path:
    project_dir = tmp_path / "myproj"
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / "myproj.gp"
    project_file.write_text(body)
    return project_file


# --- refresh_deltas_for_changespec ---------------------------------------


def test_refresh_returns_false_when_changespec_is_missing(tmp_path: Path) -> None:
    project_file = _write_project(
        tmp_path, "NAME: other\nDESCRIPTION:\n  x\nSTATUS: WIP\n\n\n"
    )
    assert (
        refresh_deltas_for_changespec(str(project_file), "missing", str(tmp_path))
        is False
    )


def test_refresh_writes_section_when_compute_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When compute_deltas returns a list, the DELTAS section is written."""
    project_file = _write_project(
        tmp_path, "NAME: feature\nDESCRIPTION:\n  test\nSTATUS: WIP\n\n\n"
    )

    def fake_compute(
        changespec: object, provider: object, cwd: str
    ) -> list[DeltaEntry]:
        return [
            DeltaEntry(path="added.py", change_type="A"),
            DeltaEntry(path="kept.py", change_type="M"),
        ]

    monkeypatch.setattr("sase.ace.deltas.refresh.compute_deltas", fake_compute)
    monkeypatch.setattr(
        "sase.ace.deltas.refresh.get_vcs_provider", lambda _cwd: object()
    )

    ok = refresh_deltas_for_changespec(str(project_file), "feature", str(tmp_path))
    assert ok is True
    body = project_file.read_text()
    assert "DELTAS:" in body
    assert "+ added.py" in body
    assert "~ kept.py" in body


def test_refresh_preserves_existing_section_on_compute_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DeltaComputationError must leave the prior DELTAS body untouched."""
    project_file = _write_project(
        tmp_path,
        "NAME: feature\n"
        "DESCRIPTION:\n  test\n"
        "STATUS: WIP\n"
        "DELTAS:\n"
        "  + previously_known.py\n"
        "\n\n",
    )

    from sase.ace.deltas import DeltaComputationError

    def fake_compute(
        changespec: object, provider: object, cwd: str
    ) -> list[DeltaEntry]:
        raise DeltaComputationError("feature", "vcs blew up")

    monkeypatch.setattr("sase.ace.deltas.refresh.compute_deltas", fake_compute)
    monkeypatch.setattr(
        "sase.ace.deltas.refresh.get_vcs_provider", lambda _cwd: object()
    )

    ok = refresh_deltas_for_changespec(str(project_file), "feature", str(tmp_path))
    assert ok is False
    assert "+ previously_known.py" in project_file.read_text()


def test_refresh_swallows_provider_lookup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_vcs_provider failure is non-fatal; existing DELTAS preserved."""
    project_file = _write_project(
        tmp_path,
        "NAME: feature\nDESCRIPTION:\n  test\nSTATUS: WIP\nDELTAS:\n  + keep.py\n\n\n",
    )

    def boom(_cwd: str) -> object:
        raise RuntimeError("no vcs here")

    monkeypatch.setattr("sase.ace.deltas.refresh.get_vcs_provider", boom)

    ok = refresh_deltas_for_changespec(str(project_file), "feature", str(tmp_path))
    assert ok is False
    assert "+ keep.py" in project_file.read_text()


# --- CLI smoke test ------------------------------------------------------


def test_sync_deltas_cli_help_includes_short_options() -> None:
    """CLI exposes -c/-p/-w short options per the project convention."""
    out = subprocess.run(
        [sys.executable, "-m", "sase", "changespec", "sync-deltas", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert "-c" in out.stdout
    assert "-p" in out.stdout
    assert "-w" in out.stdout


def test_sync_deltas_cli_reports_missing_project_file(tmp_path: Path) -> None:
    """When -p points at nonexistent file, the CLI exits non-zero with a message."""
    bogus = tmp_path / "nope.gp"
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "sase",
            "changespec",
            "sync-deltas",
            "-c",
            "feature",
            "-p",
            str(bogus),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )
    assert out.returncode != 0
    assert "project file not found" in out.stderr.lower()
