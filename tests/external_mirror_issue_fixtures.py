"""Pytest fixtures for external issue mirror tests."""

from pathlib import Path

import pytest

from sase.bead.project import BeadProject
from sase.task_types._models import TaskTypeProvenance, TaskTypeRecord, TaskTypeRegistry


def _github_task_type_registry() -> TaskTypeRegistry:
    return TaskTypeRegistry(
        records=(
            TaskTypeRecord(
                task_type="github",
                spec={"task_type": "github", "agent_creatable": False},
                digest="0" * 64,
                provenance=TaskTypeProvenance(
                    source="plugin",
                    name="github",
                    package="sase-github",
                    version="0.0.0",
                ),
            ),
        ),
        diagnostics=(),
    )


@pytest.fixture(autouse=True)
def github_task_type_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the ``github`` catalog member available without installing the plugin."""
    monkeypatch.setattr(
        "sase.external_mirror._issue_apply.get_task_type_registry",
        _github_task_type_registry,
    )


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
    from tests.test_bead.claims_test_helpers import install_writable_bead_store

    install_writable_bead_store(monkeypatch, beads_dir)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    return beads_dir
