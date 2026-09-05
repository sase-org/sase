"""Tests for the runner's post-preparation bead claim helper."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.sdd.store import SddMaterializationError, SddStore, write_sdd_store_record
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


def _seed_store(root: Path, *, beads_dirname: str = "sdd/beads") -> str:
    with BeadProject.init(root, beads_dirname=beads_dirname) as project:
        return project.create("Runner claim", IssueType.PLAN).id


def _seed_split_beads_remote(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "beads.git"
    seed = tmp_path / "beads-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    bead_id = _seed_store(seed, beads_dirname=".")
    commit_all(seed, "Initialize beads store")
    git(["push", "-u", "origin", "main"], seed)
    return remote, bead_id


def _write_split_store_record(primary: Path, beads_remote: Path) -> None:
    write_sdd_store_record(
        primary,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": str(primary.parent / "plans.git"),
                },
                "research": {
                    "repo": "owner/repo--research",
                    "remote_url": str(primary.parent / "research.git"),
                },
                "beads": {
                    "repo": "owner/repo--beads",
                    "remote_url": str(beads_remote),
                },
            },
        },
    )


def test_claim_helper_claims_in_tree_store_and_refreshes_projection(
    tmp_path: Path,
) -> None:
    bead_id = _seed_store(tmp_path)
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
    assert '"assignee":"worker"' in (tmp_path / "sdd/beads/issues.jsonl").read_text()
    commit.assert_not_called()
    publish.assert_not_called()


def test_claim_helper_commits_managed_store_and_rejects_active_reassignment(
    tmp_path: Path,
) -> None:
    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = _seed_store(sdd_dir, beads_dirname="beads")
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


def test_claim_helper_retains_force_reuse_in_progress_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = _seed_store(sdd_dir, beads_dirname="beads")
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


def test_claim_helper_rejects_force_reuse_marker_for_another_owner(
    tmp_path: Path,
) -> None:
    sdd_dir = tmp_path / ".sase/sdd"
    bead_id = _seed_store(sdd_dir, beads_dirname="beads")
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


def test_claim_helper_routes_split_store_commit_and_publish_to_beads_sidecar(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    beads.mkdir(parents=True)
    bead_id = _seed_store(beads, beads_dirname=".")
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )
    commit = MagicMock(return_value=True)
    materialize = MagicMock()
    publish = MagicMock()

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.store.ensure_sdd_kind_clone", materialize),
        patch("sase.sdd.files.commit_sdd_store_files", commit),
        patch("sase.bead.sync.publish_bead_claim", publish),
    ):
        issue = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert issue.assignee == "worker"
    materialize.assert_called_once_with(
        str(tmp_path), 2, "beads", strict=True, fresh=False
    )
    commit.assert_called_once()
    assert commit.call_args.kwargs["paths"] == [beads]
    publish.assert_called_once_with(beads, bead_id, "worker")


def test_claim_helper_materializes_cold_split_beads_store(
    tmp_path: Path,
) -> None:
    remote, bead_id = _seed_split_beads_remote(tmp_path)
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    primary.mkdir()
    workspace.mkdir()
    _write_split_store_record(primary, remote)
    plans = workspace / "sase" / "repos" / "plans"
    beads = workspace / "sase" / "repos" / "beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )
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
            workspace_dir=str(workspace),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert issue.status == Status.IN_PROGRESS
    assert issue.assignee == "worker"
    assert (beads / ".git").is_dir()
    commit.assert_called_once()
    assert commit.call_args.kwargs["paths"] == [beads]
    assert commit.call_args.kwargs["already_locked"] is True
    publish.assert_called_once_with(beads, bead_id, "worker")


def test_claim_helper_materializes_before_taking_store_lock(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )
    events: list[str] = []
    expected_issue = MagicMock()
    project = MagicMock()
    project.claim_for_agent_launch.return_value = expected_issue
    project.mutation_changed = True
    project_context = MagicMock()
    project_context.__enter__.return_value = project

    materialize_kwargs: dict[str, object] = {}

    def materialize(*_args, **kwargs) -> Path:
        materialize_kwargs.update(kwargs)
        events.append("materialize")
        beads.mkdir(parents=True)
        return beads

    @contextmanager
    def lock(root: Path):
        assert root.is_dir()
        events.append("lock")
        yield True

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.store.ensure_sdd_kind_clone", side_effect=materialize),
        patch("sase.bead.sync.bead_store_write_lock", side_effect=lock),
        patch(
            "sase.bead.store_locator.open_bead_project_for_beads_dir",
            return_value=project_context,
        ),
        patch("sase.sdd.files.commit_sdd_store_files", return_value=True),
        patch("sase.bead.sync.publish_bead_claim"),
    ):
        issue = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id="sase-1",
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert issue is expected_issue
    assert events == ["materialize", "lock"]
    assert materialize_kwargs.get("fresh", False) is False


def test_claim_helper_ensures_existing_store_before_taking_store_lock(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    beads.mkdir(parents=True)
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )
    events: list[str] = []
    expected_issue = MagicMock()
    project = MagicMock()
    project.claim_for_agent_launch.return_value = expected_issue
    project.mutation_changed = True
    project_context = MagicMock()
    project_context.__enter__.return_value = project

    def materialize(*_args, **_kwargs) -> Path:
        events.append("materialize")
        assert beads.is_dir()
        return beads

    @contextmanager
    def lock(root: Path):
        assert root.is_dir()
        events.append("lock")
        yield True

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.store.ensure_sdd_kind_clone", side_effect=materialize),
        patch("sase.bead.sync.bead_store_write_lock", side_effect=lock),
        patch(
            "sase.bead.store_locator.open_bead_project_for_beads_dir",
            return_value=project_context,
        ),
        patch("sase.sdd.files.commit_sdd_store_files", return_value=True),
        patch("sase.bead.sync.publish_bead_claim"),
    ):
        issue = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id="sase-1",
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert issue is expected_issue
    assert events == ["materialize", "lock"]


def test_claim_helper_retries_missing_issue_after_fresh_ensure(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )
    events: list[str] = []
    expected_issue = MagicMock()
    project = MagicMock()
    project.mutation_changed = True
    project_context = MagicMock()
    project_context.__enter__.return_value = project
    show_calls = 0

    def show(bead_id: str) -> MagicMock:
        nonlocal show_calls
        events.append("show")
        show_calls += 1
        if show_calls == 1:
            raise KeyError(f"Issue not found: {bead_id}")
        return MagicMock()

    def claim(bead_id: str, agent_name: str) -> MagicMock:
        events.append("claim")
        return expected_issue

    def materialize(*_args, **kwargs) -> Path:
        events.append("fresh" if kwargs.get("fresh") else "ensure")
        beads.mkdir(parents=True, exist_ok=True)
        return beads

    @contextmanager
    def lock(root: Path):
        assert root.is_dir()
        events.append("lock")
        yield True

    def commit(*_args, **_kwargs) -> bool:
        events.append("commit")
        return True

    project.show.side_effect = show
    project.claim_for_agent_launch.side_effect = claim

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.store.ensure_sdd_kind_clone", side_effect=materialize),
        patch("sase.bead.sync.bead_store_write_lock", side_effect=lock),
        patch(
            "sase.bead.store_locator.open_bead_project_for_beads_dir",
            return_value=project_context,
        ),
        patch("sase.sdd.files.commit_sdd_store_files", side_effect=commit),
        patch("sase.bead.sync.publish_bead_claim"),
    ):
        issue = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id="sase-1",
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert issue is expected_issue
    assert events == [
        "ensure",
        "lock",
        "show",
        "fresh",
        "lock",
        "show",
        "claim",
        "commit",
    ]


def test_claim_helper_fresh_retry_still_fails_when_bead_is_missing(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )
    events: list[str] = []
    project = MagicMock()
    project_context = MagicMock()
    project_context.__enter__.return_value = project

    def show(bead_id: str) -> MagicMock:
        events.append("show")
        raise KeyError(f"Issue not found: {bead_id}")

    def materialize(*_args, **kwargs) -> Path:
        events.append("fresh" if kwargs.get("fresh") else "ensure")
        beads.mkdir(parents=True, exist_ok=True)
        return beads

    @contextmanager
    def lock(root: Path):
        events.append("lock")
        yield True

    project.show.side_effect = show

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.store.ensure_sdd_kind_clone", side_effect=materialize),
        patch("sase.bead.sync.bead_store_write_lock", side_effect=lock),
        patch(
            "sase.bead.store_locator.open_bead_project_for_beads_dir",
            return_value=project_context,
        ),
        pytest.raises(RuntimeError, match=r"sase-1.*worker.*Issue not found: sase-1"),
    ):
        claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id="sase-1",
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert events == ["ensure", "lock", "show", "fresh", "lock", "show"]
    project.claim_for_agent_launch.assert_not_called()


def test_claim_helper_leaves_schema_two_sidecar_layout_unchanged(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    bead_id = _seed_store(plans, beads_dirname="beads")
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
    )
    materialize = MagicMock()

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.store.ensure_sdd_kind_clone", materialize),
        patch("sase.sdd.files.commit_sdd_store_files", return_value=True),
        patch("sase.bead.sync.publish_bead_claim"),
    ):
        issue = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert issue.assignee == "worker"
    materialize.assert_called_once_with(
        str(tmp_path), 2, "beads", strict=True, fresh=False
    )
    assert not (tmp_path / "sase" / "repos" / "beads").exists()


def test_claim_helper_surfaces_beads_sidecar_materialization_failure(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )
    failure = SddMaterializationError(
        "could not materialize beads sidecar repository owner/repo--beads "
        "from git@example.com:owner/repo--beads.git"
    )

    with (
        patch("sase.sdd.store.resolve_sdd_store", return_value=store),
        patch("sase.sdd.store.ensure_sdd_kind_clone", side_effect=failure),
        pytest.raises(RuntimeError) as exc_info,
    ):
        claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id="sase-1",
            workspace_dir=str(tmp_path),
            workspace_num=2,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    message = str(exc_info.value)
    assert "owner/repo--beads" in message
    assert "git@example.com:owner/repo--beads.git" in message
    assert "Run 'sase bead init' first" not in message


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
