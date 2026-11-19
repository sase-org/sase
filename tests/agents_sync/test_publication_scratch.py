"""Root-level publisher apply scratch is swept after family restore."""

from __future__ import annotations

from pathlib import Path
import logging

import pytest

from sase.agents_sync.git import run_git
from sase.agents_sync.git_sync import clean_agents_payload_worktree
from sase.agents_sync.publication_scratch import (
    is_publication_scratch_path,
    list_publication_scratch_dirs,
    sweep_publication_scratch,
)
from tests.agents_sync.commit_publication_fixtures import git, setup_target


def test_is_publication_scratch_path_matches_root_stage_and_backup() -> None:
    assert is_publication_scratch_path(".sase-v2-stage-abc")
    assert is_publication_scratch_path(".sase-v2-backup-abc/README.md")
    assert is_publication_scratch_path("./.sase-v2-stage-abc/payload.json")
    assert not is_publication_scratch_path("prompts/202611/agent.md")
    assert not is_publication_scratch_path("README.md")


def test_sweep_publication_scratch_removes_each_directory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repo = tmp_path / "sidecar"
    repo.mkdir()
    stage = repo / ".sase-v2-stage-abc"
    backup = repo / ".sase-v2-backup-abc"
    stage.mkdir()
    (stage / "README.md").write_text("staged\n")
    backup.mkdir()
    (backup / "README.md").write_text("backup\n")
    (repo / "README.md").write_text("keep\n")

    caplog.set_level(logging.INFO)
    assert sweep_publication_scratch(repo) is None
    assert list_publication_scratch_dirs(repo) == ()
    assert not stage.exists()
    assert not backup.exists()
    assert (repo / "README.md").read_text() == "keep\n"
    assert any(
        "removed stranded publication scratch" in rec.message for rec in caplog.records
    )


def test_payload_clean_sweeps_scratch_after_family_restore(tmp_path: Path) -> None:
    target, _remote = setup_target(tmp_path)
    repo = target.sidecar_path
    git(repo, "config", "user.name", "Tests")
    git(repo, "config", "user.email", "tests@example.test")
    stage = repo / ".sase-v2-stage-abc"
    backup = repo / ".sase-v2-backup-abc"
    stage.mkdir()
    (stage / "README.md").write_text("staged\n")
    backup.mkdir()
    (backup / "README.md").write_text("backup\n")

    assert clean_agents_payload_worktree(repo, run_git) is None
    assert not stage.exists()
    assert not backup.exists()
