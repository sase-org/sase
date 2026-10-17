"""Shared setup helpers for runner bead claim tests."""

from pathlib import Path

from sase.bead.model import IssueType
from sase.bead.project import BeadProject


def seed_store(root: Path, *, beads_dirname: str = "sdd/beads") -> str:
    with BeadProject.init(root, beads_dirname=beads_dirname) as project:
        return project.create("Runner claim", IssueType.PLAN).id
