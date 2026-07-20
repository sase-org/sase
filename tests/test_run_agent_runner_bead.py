"""Tests for the runner's post-preparation bead claim helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore


def _seed_store(root: Path, *, beads_dirname: str = "sdd/beads") -> str:
    with BeadProject.init(root, beads_dirname=beads_dirname) as project:
        return project.create("Runner claim", IssueType.PLAN).id


def test_claim_helper_claims_in_tree_store_and_refreshes_projection(
    tmp_path: Path,
) -> None:
    bead_id = _seed_store(tmp_path)
    store = SddStore(
        storage="in_tree",
        sdd_dir=tmp_path / "sdd",
        repo_root=tmp_path / "sdd",
    )

    with patch("sase.sdd.store.resolve_sdd_store", return_value=store):
        issue = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=1,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert issue.status == Status.IN_PROGRESS
    assert issue.assignee == "worker"
    with BeadProject(tmp_path) as project:
        assert project.show(bead_id).assignee == "worker"
    assert '"assignee":"worker"' in (tmp_path / "sdd/beads/issues.jsonl").read_text()


def test_claim_helper_commits_managed_store_and_allows_reassignment(
    tmp_path: Path,
) -> None:
    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = _seed_store(sdd_dir, beads_dirname="beads")
    store = SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)
    commit = MagicMock(return_value=True)

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", commit),
    ):
        first = claim_bead_for_agent_launch(
            agent_name="worker.1",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )
        second = claim_bead_for_agent_launch(
            agent_name="worker.2",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert first.assignee == "worker.1"
    assert second.assignee == "worker.2"
    assert commit.call_count == 2
    assert commit.call_args.kwargs["auto_commit_type"] == "beads"
    assert commit.call_args.kwargs["paths"] == [sdd_dir / "beads"]
    assert commit.call_args.kwargs["artifacts_dir"] == tmp_path / "artifacts"


@pytest.mark.parametrize("failure", ["missing", "closed"])
def test_claim_helper_wraps_bead_mutation_errors(
    tmp_path: Path,
    failure: str,
) -> None:
    bead_id = _seed_store(tmp_path)
    if failure == "missing":
        bead_id = "missing-1"
    else:
        with BeadProject(tmp_path) as project:
            project.close([bead_id])
    store = SddStore(
        storage="in_tree",
        sdd_dir=tmp_path / "sdd",
        repo_root=tmp_path / "sdd",
    )

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        pytest.raises(RuntimeError, match=rf"{bead_id}.*worker"),
    ):
        claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=1,
            artifacts_dir=str(tmp_path / "artifacts"),
        )


def test_claim_helper_wraps_store_and_commit_failures(tmp_path: Path) -> None:
    with (
        patch("sase.sdd.store.resolve_sdd_store", side_effect=OSError("no store")),
        pytest.raises(RuntimeError, match="sase-8f.2.*worker.*no store"),
    ):
        claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id="sase-8f.2",
            workspace_dir=str(tmp_path),
            workspace_num=1,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = _seed_store(sdd_dir, beads_dirname="beads")
    store = SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)
    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", return_value=False),
        pytest.raises(RuntimeError, match=rf"{bead_id}.*worker.*no local SDD commit"),
    ):
        claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )
