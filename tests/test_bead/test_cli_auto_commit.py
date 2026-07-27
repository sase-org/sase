"""Auto-commit coverage for mutating ``sase bead`` commands."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_common import auto_commit_bead_store
from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore
from sase.sdd.store import write_sdd_store_record
from tests.sdd_policy_helpers import set_sdd_policy


def test_auto_commit_bead_store_commits_non_in_tree_beads_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "project"
    workspace = tmp_path / "project_2"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    sdd_dir = workspace / ".sase" / "sdd"
    (sdd_dir / "beads").mkdir(parents=True)
    _write_checkout_marker(workspace, primary, workspace_num=2)
    _set_sdd_config(monkeypatch, storage="separate_repo")
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

    monkeypatch.chdir(workspace)
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", fake_commit)

    auto_commit_bead_store("chore(beads): close beads-1")

    assert len(commit_calls) == 1
    store = commit_calls[0]["store"]
    assert isinstance(store, SddStore)
    assert store.storage == "separate_repo"
    assert store.sdd_dir == sdd_dir
    assert commit_calls == [
        {
            "store": store,
            "message": "chore(beads): close beads-1",
            "auto_commit_type": "beads",
            "paths": [sdd_dir / "beads"],
        }
    ]


def test_auto_commit_bead_store_skips_in_tree_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "project"
    workspace = tmp_path / "project_2"
    (primary / "sdd" / "beads").mkdir(parents=True)
    (workspace / "sdd" / "beads").mkdir(parents=True)
    _write_checkout_marker(workspace, primary, workspace_num=2)
    _set_sdd_config(monkeypatch, storage="in_tree")
    commit = MagicMock()

    monkeypatch.chdir(workspace)
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)

    auto_commit_bead_store("chore(beads): update beads-1")

    commit.assert_not_called()


def test_auto_commit_bead_store_swallows_commit_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary = tmp_path / "project"
    workspace = tmp_path / "project_2"
    sdd_dir = primary / ".sase" / "sdd"
    (sdd_dir / "beads").mkdir(parents=True)
    (workspace / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_checkout_marker(workspace, primary, workspace_num=2)
    _set_sdd_config(monkeypatch, storage="local")

    def fail_commit(*_: object, **__: object) -> bool:
        raise RuntimeError("git is unavailable")

    monkeypatch.chdir(workspace)
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", fail_commit)

    with caplog.at_level(logging.WARNING, logger="sase.bead.cli_common"):
        auto_commit_bead_store("chore(beads): update beads-1")

    assert "Failed to auto-commit SDD bead store changes" in caplog.text


def test_bead_create_in_separate_repo_writes_and_commits_workspace_local_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primary = tmp_path / "project"
    workspace = tmp_path / "project_2"
    primary_sdd = primary / ".sase" / "sdd"
    workspace_sdd = workspace / ".sase" / "sdd"
    primary_sdd.mkdir(parents=True)
    workspace_sdd.mkdir(parents=True)
    _init_git_repo(primary_sdd)
    _init_git_repo(workspace_sdd)
    write_sdd_store_record(
        primary,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "owner/project--sdd",
            "discovery": "found",
        },
    )
    _write_checkout_marker(workspace, primary, workspace_num=2)
    _set_sdd_config(monkeypatch, storage="separate_repo")
    monkeypatch.chdir(workspace)

    with BeadProject.init(workspace_sdd, beads_dirname="beads"):
        pass
    plan = workspace_sdd / "plans" / "202607" / "round_trip.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Round trip\n", encoding="utf-8")
    _git(workspace_sdd, "add", ".")
    _git(workspace_sdd, "commit", "-m", "Initialize workspace SDD")
    assert _git_status(workspace_sdd) == ""

    args = argparse.Namespace(
        type=f"plan({plan})",
        changespec=None,
        bug_id=None,
        tier=None,
        title="Created",
        description=None,
        assignee=None,
        model=None,
    )
    from sase.sdd.files import commit_sdd_store_files as real_commit
    from sase.sdd._git_contention import store_write_lock_is_held

    commit_lock_observations: list[tuple[bool, bool]] = []

    def recording_commit(store_arg, message, **kwargs):
        commit_lock_observations.append(
            (
                bool(kwargs.get("already_locked")),
                store_write_lock_is_held(store_arg.repo_root),
            )
        )
        return real_commit(store_arg, message, **kwargs)

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", recording_commit)

    bead_cli.handle_bead_create(args)

    assert "Created plan:" in capsys.readouterr().out
    assert commit_lock_observations == [(True, True)]
    assert _git_status(workspace_sdd) == ""
    log = _git(workspace_sdd, "log", "--oneline", "-1").stdout
    assert "chore(beads): create" in log
    assert (workspace_sdd / "beads" / "issues.jsonl").exists()
    assert not (primary_sdd / "beads" / "issues.jsonl").exists()


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
                model=None,
            )
        )

    auto_commit.assert_called_once_with(
        f"chore(beads): update {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_handle_bead_open_auto_commit_message(project_dir: Path) -> None:
    issue = _create_issue(project_dir, "Reopened")
    with BeadProject(project_dir) as proj:
        proj.close([issue.id], reason="done")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_open(argparse.Namespace(id=issue.id))

    auto_commit.assert_called_once_with(
        f"chore(beads): reopen {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_handle_bead_close_auto_commit_message(project_dir: Path) -> None:
    issue = _create_issue(project_dir, "Closed")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_close(argparse.Namespace(ids=[issue.id], reason="done"))

    auto_commit.assert_called_once_with(
        f"chore(beads): close {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_handle_bead_rm_auto_commit_message_includes_all_requested_ids(
    project_dir: Path,
) -> None:
    first = _create_issue(project_dir, "Removed first")
    second = _create_issue(project_dir, "Removed second")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_rm(argparse.Namespace(ids=[first.id, second.id]))

    auto_commit.assert_called_once_with(
        f"chore(beads): remove {first.id} {second.id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_handle_bead_rm_missing_id_does_not_remove_or_commit(
    project_dir: Path,
) -> None:
    issue = _create_issue(project_dir, "Preserved")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        with pytest.raises(SystemExit, match="1"):
            bead_cli.handle_bead_rm(argparse.Namespace(ids=[issue.id, "missing"]))

    auto_commit.assert_not_called()
    with BeadProject(project_dir) as project:
        assert project.show(issue.id).id == issue.id


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
        f"chore(beads): link {blocked.id} -> {dependency.id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_rollback_work_launch_auto_commits_cleanup() -> None:
    from sase.bead.cli_work_cleanup import rollback_work_launch

    proj = MagicMock()

    with patch("sase.bead.cli_work_cleanup.auto_commit_bead_store") as auto_commit:
        rollback_work_launch(
            proj,
            "epic-1",
            marked_ready_this_run=True,
        )

    proj.update.assert_not_called()
    proj.unmark_ready_to_work.assert_called_once_with("epic-1")
    auto_commit.assert_called_once_with(
        "chore(beads): recover failed work launch epic-1"
    )


def test_rollback_work_launch_suppresses_push_when_requested() -> None:
    from sase.bead.cli_work_cleanup import rollback_work_launch

    proj = MagicMock()

    with patch("sase.bead.cli_work_cleanup.auto_commit_bead_store") as auto_commit:
        rollback_work_launch(
            proj,
            "epic-1",
            marked_ready_this_run=False,
            no_push=True,
        )

    auto_commit.assert_called_once_with(
        "chore(beads): recover failed work launch epic-1",
        push_after_commit=False,
    )


def _create_issue(project_dir: Path, title: str) -> Issue:
    with BeadProject(project_dir) as proj:
        return proj.create(title, IssueType.PLAN)


def _set_sdd_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    storage: str,
) -> None:
    set_sdd_policy(monkeypatch, storage)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )


def _write_checkout_marker(
    checkout: Path,
    primary: Path,
    *,
    workspace_num: int,
    project_name: str = "project",
) -> None:
    marker = {
        "project_name": project_name,
        "project_key": project_name,
        "workspace_num": workspace_num,
        "primary_workspace_dir": str(primary),
        "registry_path": str(primary / ".sase" / "registry.json"),
        "schema_version": 1,
    }
    marker_dir = checkout / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(marker),
        encoding="utf-8",
    )


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.name", "SASE Test")
    _git(path, "config", "user.email", "sase-test@example.invalid")


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def _git_status(path: Path) -> str:
    return _git(path, "status", "--porcelain").stdout
