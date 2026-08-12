"""Pytest fixtures for external issue mirror tests."""

from pathlib import Path

import pytest

from sase.bead.project import BeadProject


@pytest.fixture
def bead_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "bead-store"
    with BeadProject.init(root):
        pass
    beads_dir = root / "sdd" / "beads"
    monkeypatch.setattr(
        "sase.external_mirror.issues.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    return beads_dir
