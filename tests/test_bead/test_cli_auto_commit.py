"""Auto-commit coverage for mutating ``sase bead`` commands."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_common import auto_commit_bead_store
from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore


def test_auto_commit_bead_store_commits_non_in_tree_beads_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SddStore(storage="separate_repo", sdd_dir=tmp_path, repo_root=tmp_path)
    commit_calls: list[dict[str, object]] = []

    def fake_commit(
        store_arg: SddStore,
        message: str,
        *,
        auto_commit_type: str,
        paths: list[Path],
    ) -> bool:
        commit_calls.append(
            {
                "store": store_arg,
                "message": message,
                "auto_commit_type": auto_commit_type,
                "paths": paths,
            }
        )
        return True

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_: store)
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", fake_commit)

    auto_commit_bead_store("chore(beads): close beads-1")

    assert commit_calls == [
        {
            "store": store,
            "message": "chore(beads): close beads-1",
            "auto_commit_type": "beads",
            "paths": [tmp_path / "beads"],
        }
    ]


def test_auto_commit_bead_store_skips_in_tree_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SddStore(storage="in_tree", sdd_dir=tmp_path / "sdd", repo_root=tmp_path)
    commit = MagicMock()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_: store)
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)

    auto_commit_bead_store("chore(beads): update beads-1")

    commit.assert_not_called()


def test_auto_commit_bead_store_swallows_commit_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SddStore(storage="local", sdd_dir=tmp_path, repo_root=tmp_path)

    def fail_commit(*_: object, **__: object) -> bool:
        raise RuntimeError("git is unavailable")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_: store)
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", fail_commit)

    with caplog.at_level(logging.WARNING, logger="sase.bead.cli_common"):
        auto_commit_bead_store("chore(beads): update beads-1")

    assert "Failed to auto-commit SDD bead store changes" in caplog.text


def test_handle_bead_create_auto_commit_message(
    project_dir: Path,
) -> None:
    plan = project_dir / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    args = argparse.Namespace(
        type=f"plan({plan})",
        changespec=None,
        bug_id=None,
        tier=None,
        epic_count=None,
        title="Created",
        description=None,
        assignee=None,
        model=None,
    )

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_create(args)

    message = auto_commit.call_args.args[0]
    assert message.startswith("chore(beads): create ")


def test_handle_bead_update_auto_commit_message(project_dir: Path) -> None:
    issue = _create_issue(project_dir, "Updated")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_update(
            argparse.Namespace(
                id=issue.id,
                status=None,
                title="Updated title",
                description=None,
                notes=None,
                design=None,
                assignee=None,
                tier=None,
                epic_count=None,
                model=None,
            )
        )

    auto_commit.assert_called_once_with(f"chore(beads): update {issue.id}")


def test_handle_bead_open_auto_commit_message(project_dir: Path) -> None:
    issue = _create_issue(project_dir, "Reopened")
    with BeadProject(project_dir) as proj:
        proj.close([issue.id], reason="done")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_open(argparse.Namespace(id=issue.id))

    auto_commit.assert_called_once_with(f"chore(beads): reopen {issue.id}")


def test_handle_bead_close_auto_commit_message(project_dir: Path) -> None:
    issue = _create_issue(project_dir, "Closed")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_close(argparse.Namespace(ids=[issue.id], reason="done"))

    auto_commit.assert_called_once_with(f"chore(beads): close {issue.id}")


def test_handle_bead_rm_auto_commit_message(project_dir: Path) -> None:
    issue = _create_issue(project_dir, "Removed")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_rm(argparse.Namespace(id=issue.id))

    auto_commit.assert_called_once_with(f"chore(beads): remove {issue.id}")


def test_handle_bead_dep_add_auto_commit_message(project_dir: Path) -> None:
    blocked = _create_issue(project_dir, "Blocked")
    dependency = _create_issue(project_dir, "Dependency")

    with patch("sase.bead.cli_admin.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_dep(
            argparse.Namespace(
                dep_action="add",
                issue=blocked.id,
                depends_on=dependency.id,
            )
        )

    auto_commit.assert_called_once_with(
        f"chore(beads): link {blocked.id} -> {dependency.id}"
    )


def test_rollback_work_launch_auto_commits_cleanup() -> None:
    from sase.bead.cli_work_cleanup import rollback_work_launch

    proj = MagicMock()

    with patch("sase.bead.cli_work_cleanup.auto_commit_bead_store") as auto_commit:
        rollback_work_launch(
            proj,
            "epic-1",
            [("phase-1", Status.IN_PROGRESS, "agent")],
            unmark_ready=True,
        )

    proj.update.assert_called_once_with(
        "phase-1",
        status=Status.IN_PROGRESS.value,
        assignee="agent",
    )
    proj.unmark_ready_to_work.assert_called_once_with("epic-1")
    auto_commit.assert_called_once_with("chore(beads): rollback work launch epic-1")


def _create_issue(project_dir: Path, title: str) -> Issue:
    with BeadProject(project_dir) as proj:
        return proj.create(title, IssueType.PLAN)
