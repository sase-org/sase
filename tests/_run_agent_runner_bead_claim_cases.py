"""Runner bead claim cases for in-tree and closed beads."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore
from tests._run_agent_runner_bead_helpers import seed_store


def case_claim_helper_claims_in_tree_store_and_export_reflects_claim(
    tmp_path: Path,
) -> None:
    bead_id = seed_store(tmp_path)
    store = SddStore(
        storage="in_tree",
        sdd_dir=tmp_path / "sdd",
        repo_root=tmp_path / "sdd",
    )
    commit = MagicMock()
    publish = MagicMock()

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", commit),
        patch("sase.bead.sync.publish_bead_claim", publish),
    ):
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
        # Projection-off: the claim no longer rewrites issues.jsonl, so
        # export explicitly before asserting on the projected content.
        project._export()
    assert '"assignee":"worker"' in (tmp_path / "sdd/beads/issues.jsonl").read_text()
    commit.assert_not_called()
    publish.assert_not_called()


def case_claim_helper_records_closed_launch_with_distinct_commit_subject(
    tmp_path: Path,
) -> None:
    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = seed_store(sdd_dir, beads_dirname="beads")
    with BeadProject(sdd_dir, beads_dirname="beads") as project:
        project.close([bead_id], reason="done")
    store = SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)
    commit = MagicMock(return_value=True)
    publish = MagicMock()

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", commit),
        patch("sase.bead.sync.publish_bead_claim", publish),
    ):
        issue = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
            submitted_at="2999-01-01T00:00:00Z",
            run_id="260101_000200",
        )

    assert issue.status is Status.CLOSED
    assert issue.notes[-1].text.startswith("CLOSED-BEAD LAUNCH:")
    assert commit.call_args.args[1] == (
        f"chore(beads): note closed-bead launch of {bead_id} for worker"
    )
    publish.assert_called_once_with(sdd_dir / "beads", bead_id, "worker")


def case_force_reuse_closed_bead_attaches_without_changing_prior_assignee(
    tmp_path: Path,
) -> None:
    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = seed_store(sdd_dir, beads_dirname="beads")
    with BeadProject(sdd_dir, beads_dirname="beads") as project:
        project.update(bead_id, assignee="prior-owner")
        project.close([bead_id], reason="completed before restart")
        closed_before = project.show(bead_id)
    store = SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)
    commit = MagicMock(return_value=True)

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", commit),
        patch("sase.bead.sync.publish_bead_claim"),
    ):
        attached = claim_bead_for_agent_launch(
            agent_name="replacement",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
            force_reuse_prior_owner="prior-owner",
            submitted_at="2999-01-01T00:00:00Z",
            run_id="260101_000200",
        )

    assert attached.status is Status.CLOSED
    assert attached.assignee == closed_before.assignee == "prior-owner"
    assert attached.closed_at == closed_before.closed_at
    assert attached.resolution == closed_before.resolution
    assert attached.notes[-1].author == "replacement"
    assert attached.notes[-1].text.startswith("CLOSED-BEAD LAUNCH:")
    assert commit.call_args.args[1] == (
        f"chore(beads): note closed-bead launch of {bead_id} for replacement"
    )


def case_claim_helper_commits_managed_store_and_rejects_active_reassignment(
    tmp_path: Path,
) -> None:
    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = seed_store(sdd_dir, beads_dirname="beads")
    store = SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)
    commit = MagicMock(return_value=True)
    publish = MagicMock()

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", commit),
        patch("sase.bead.sync.publish_bead_claim", publish),
    ):
        first = claim_bead_for_agent_launch(
            agent_name="worker.1",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )
        with pytest.raises(RuntimeError, match="already in_progress"):
            claim_bead_for_agent_launch(
                agent_name="worker.2",
                bead_id=bead_id,
                workspace_dir=str(tmp_path),
                workspace_num=2,
                artifacts_dir=str(tmp_path / "artifacts"),
            )
        repeated = claim_bead_for_agent_launch(
            agent_name="worker.1",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert first.assignee == "worker.1"
    assert repeated.assignee == "worker.1"
    assert commit.call_count == 1
    assert commit.call_args.kwargs["auto_commit_type"] == "beads"
    assert commit.call_args.kwargs["paths"] == [sdd_dir / "beads"]
    assert commit.call_args.kwargs["push_after_commit"] is False
    assert commit.call_args.kwargs["artifacts_dir"] == tmp_path / "artifacts"
    assert publish.call_args_list == [
        call(sdd_dir / "beads", bead_id, "worker.1"),
    ]


def case_claim_helper_retains_force_reuse_in_progress_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = seed_store(sdd_dir, beads_dirname="beads")
    with BeadProject(sdd_dir, beads_dirname="beads") as project:
        project.update(
            bead_id,
            status=Status.IN_PROGRESS.value,
            assignee="alice.athena.worker",
        )
    store = SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)
    commit = MagicMock(return_value=True)
    publish = MagicMock()
    identity = AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"), ("athena",))
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", commit),
        patch("sase.bead.sync.publish_bead_claim", publish),
    ):
        issue = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
            force_reuse_prior_owner="athena.worker",
        )

    assert issue.status == Status.IN_PROGRESS
    assert issue.assignee == "alice.athena.worker"
    commit.assert_not_called()
    publish.assert_not_called()


def case_claim_helper_rejects_force_reuse_marker_for_another_owner(
    tmp_path: Path,
) -> None:
    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = seed_store(sdd_dir, beads_dirname="beads")
    with BeadProject(sdd_dir, beads_dirname="beads") as project:
        project.update(
            bead_id,
            status=Status.IN_PROGRESS.value,
            assignee="active",
        )
    store = SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)
    commit = MagicMock(return_value=True)
    publish = MagicMock()

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.files.commit_sdd_store_files", commit),
        patch("sase.bead.sync.publish_bead_claim", publish),
        pytest.raises(RuntimeError, match="already in_progress"),
    ):
        claim_bead_for_agent_launch(
            agent_name="replacement",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
            force_reuse_prior_owner="replacement",
        )

    commit.assert_not_called()
    publish.assert_not_called()
