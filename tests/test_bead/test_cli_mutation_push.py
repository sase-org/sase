"""Deferred push coverage for mutating ``sase bead`` commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_common import _push_committed_bead_store, bead_store_mutation
from sase.bead.cli_location import BeadsLocation
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC, BEADS_DIRNAME_ROOT
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from sase.sdd.store import SddStore


def test_sidecar_post_commit_push_is_enqueued_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync.models import ProjectTarget
    from sase.agents_sync.publication_outbox import list_agent_publications
    from sase.sdd._commit_store import push_sdd_store_after_commit

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    repo = tmp_path / "project--beads"
    target = ProjectTarget(
        project_key="proj",
        project="Project",
        primary_checkout=tmp_path / "primary",
        primary_roots=(tmp_path / "primary",),
        sidecar_path=tmp_path / "agents",
        remote_url="git@example.test:acme/project--agents.git",
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_sidecar_publication_target",
        lambda **_kwargs: (target, None),
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda *_args, **_kwargs: pytest.fail("synchronous push must not run"),
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch_async",
        lambda *_args, **_kwargs: pytest.fail("async subprocess must not run"),
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=repo,
        repo_root=repo,
        sidecar_role="beads",
    )

    push_sdd_store_after_commit(store, push_after_commit=True)

    [request] = list_agent_publications("proj")
    assert request.kind == "sidecar_push"
    assert request.sidecar_kind == "beads"


def test_deferred_push_routes_split_beads_to_beads_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = tmp_path / "project--plans"
    beads = tmp_path / "project--beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.com:acme/project--plans.git",
        beads_dir=beads,
        beads_remote_url="git@example.com:acme/project--beads.git",
    )
    location = BeadsLocation(
        root=beads,
        beads_dirname=BEADS_DIRNAME_ROOT,
        storage=store.storage,
        store=store,
    )
    push = MagicMock()
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        lambda **_kwargs: location,
    )
    monkeypatch.setattr(
        "sase.sdd._commit_store.push_sdd_store_after_commit",
        push,
    )

    _push_committed_bead_store()

    push.assert_called_once()
    pushed_store = push.call_args.args[0]
    assert pushed_store.repo_root == beads
    assert pushed_store.sidecar_role == "beads"
    assert push.call_args.kwargs == {"push_after_commit": None}


def test_deferred_push_keeps_separate_repo_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "project--sdd"
    store = SddStore(
        storage="separate_repo",
        sdd_dir=repo,
        repo_root=repo,
    )
    location = BeadsLocation(
        root=repo,
        beads_dirname=BEADS_DIRNAME_NON_VC,
        storage=store.storage,
        store=store,
    )
    push = MagicMock()
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        lambda **_kwargs: location,
    )
    monkeypatch.setattr(
        "sase.sdd._commit_store.push_sdd_store_after_commit",
        push,
    )

    _push_committed_bead_store()

    push.assert_called_once_with(store, push_after_commit=None)


def test_deferred_push_still_skips_in_tree_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SddStore(
        storage="in_tree",
        sdd_dir=tmp_path / "sdd",
        repo_root=tmp_path,
    )
    location = BeadsLocation(
        root=tmp_path,
        beads_dirname=BEADS_DIRNAME,
        storage=store.storage,
        store=store,
    )
    push = MagicMock()
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        lambda **_kwargs: location,
    )
    monkeypatch.setattr(
        "sase.sdd._commit_store.push_sdd_store_after_commit",
        push,
    )

    _push_committed_bead_store()

    push.assert_not_called()


def test_bead_store_mutation_no_push_still_commits(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auto_commit = MagicMock(return_value=True)
    push = MagicMock()
    monkeypatch.setattr(
        "sase.bead.cli_common._push_committed_bead_store",
        push,
    )

    with bead_store_mutation(auto_commit, no_push=True) as mutation:
        issue = mutation.project.create("Local close", IssueType.PLAN)
        mutation.commit(f"chore(beads): create {issue.id}")

    auto_commit.assert_called_once_with(
        f"chore(beads): create {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )
    push.assert_not_called()


def test_bead_store_mutation_routes_explicit_cwd_to_commit_and_push(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit_calls: list[tuple[str, dict[str, object]]] = []
    push = MagicMock()

    def auto_commit(message: str, **kwargs: object) -> bool:
        commit_calls.append((message, kwargs))
        return True

    monkeypatch.setattr(
        "sase.bead.cli_common._push_committed_bead_store",
        push,
    )

    with bead_store_mutation(auto_commit, cwd=project_dir) as mutation:
        issue = mutation.project.create(
            "Cross-project close", IssueType.TASK, size="small"
        )
        mutation.commit(f"chore(beads): create {issue.id}")

    assert commit_calls == [
        (
            f"chore(beads): create {issue.id}",
            {
                "push_after_commit": False,
                "already_locked": False,
                "cwd": project_dir,
            },
        )
    ]
    push.assert_called_once_with(cwd=project_dir)


def test_handle_bead_close_no_push_commits_without_push(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Local close", IssueType.PLAN)
    auto_commit = MagicMock(return_value=True)
    push = MagicMock()
    monkeypatch.setattr("sase.bead.cli_crud.auto_commit_bead_store", auto_commit)
    monkeypatch.setattr(
        "sase.bead.cli_common._push_committed_bead_store",
        push,
    )

    bead_cli.handle_bead_close(
        argparse.Namespace(ids=[issue.id], reason="done", no_push=True)
    )

    auto_commit.assert_called_once_with(
        f"chore(beads): close {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )
    push.assert_not_called()


def test_handle_bead_close_legacy_namespace_still_pushes(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Published close", IssueType.PLAN)
    auto_commit = MagicMock(return_value=True)
    push = MagicMock()
    monkeypatch.setattr("sase.bead.cli_crud.auto_commit_bead_store", auto_commit)
    monkeypatch.setattr(
        "sase.bead.cli_common._push_committed_bead_store",
        push,
    )

    bead_cli.handle_bead_close(argparse.Namespace(ids=[issue.id], reason="done"))

    auto_commit.assert_called_once_with(
        f"chore(beads): close {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )
    push.assert_called_once_with()


def test_handle_bead_update_multi_id_commits_once_and_pushes_once(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject(project_dir) as project:
        first = project.create("First", IssueType.TASK, size="small")
        second = project.create("Second", IssueType.TASK, size="small")
    auto_commit = MagicMock(return_value=True)
    push = MagicMock()
    monkeypatch.setattr("sase.bead.cli_crud.auto_commit_bead_store", auto_commit)
    monkeypatch.setattr(
        "sase.bead.cli_common._push_committed_bead_store",
        push,
    )

    bead_cli.handle_bead_update(
        argparse.Namespace(
            ids=[first.id, second.id],
            status="in_progress",
            title=None,
            description=None,
            notes=None,
            design=None,
            assignee=None,
            tier=None,
            model=None,
        )
    )

    auto_commit.assert_called_once_with(
        f"chore(beads): update {first.id} {second.id}",
        push_after_commit=False,
        already_locked=False,
    )
    push.assert_called_once_with()


def test_close_parser_accepts_no_push_short_and_long_options() -> None:
    parser = create_parser()

    short_args = parser.parse_args(["bead", "close", "sase-1", "-P"])
    long_args = parser.parse_args(["bead", "close", "sase-1", "--no-push"])
    default_args = parser.parse_args(["bead", "close", "sase-1"])

    assert short_args.no_push is True
    assert long_args.no_push is True
    assert default_args.no_push is False
