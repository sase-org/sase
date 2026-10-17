"""Tests for journaled, recoverable SASE management setup."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from sase.project_onboarding import manage
from sase.project_onboarding.journal import (
    lookup_journal,
    record_intent,
    set_journal_status,
)

_IDENTITY = "github.com/sase-org/bob"
_FINGERPRINT = "f" * 64


def _git(
    path: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Onboarding Test",
            "GIT_AUTHOR_EMAIL": "onboarding@example.test",
            "GIT_COMMITTER_NAME": "Onboarding Test",
            "GIT_COMMITTER_EMAIL": "onboarding@example.test",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=path,
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


@pytest.fixture
def onboarding_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    bare.mkdir()
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(bare))
    seed.mkdir()
    _git(seed, "init", "--initial-branch=main")
    _git(seed, "config", "user.name", "Onboarding Test")
    _git(seed, "config", "user.email", "onboarding@example.test")
    config = seed / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("# project settings\nname: bob\n", encoding="utf-8")
    _git(seed, "add", "sase/sase.yml")
    _git(seed, "commit", "-m", "initial project config")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", str(bare), str(checkout))
    _git(checkout, "config", "user.name", "Onboarding Test")
    _git(checkout, "config", "user.email", "onboarding@example.test")
    monkeypatch.setattr(
        manage.workspace_provider,
        "parse_repo_ref",
        lambda workflow, ref: SimpleNamespace(identity_key=_IDENTITY),
    )
    target = {
        "workflow_type": "gh",
        "identity_key": _IDENTITY,
        "ref": "sase-org/bob",
        "display": "sase-org/bob",
        "checkout_dir": str(checkout),
    }
    remote = {
        "default_branch": "main",
        "can_push": True,
        "sase_managed": False,
    }
    record_intent(
        identity_key=_IDENTITY,
        ref="sase-org/bob",
        display="sase-org/bob",
        workflow_type="gh",
        mode="add",
        intent_fingerprint=_FINGERPRINT,
        setup_required=True,
    )
    return {"bare": bare, "checkout": checkout, "target": target, "remote": remote}


def _manage(repo: dict[str, Any]) -> dict[str, Any]:
    return manage.manage_repository(
        repo["target"],
        repo["remote"],
        intent_fingerprint=_FINGERPRINT,
    )


def test_management_commits_and_pushes_only_marker(
    onboarding_repo: dict[str, Any],
) -> None:
    repo = onboarding_repo
    checkout: Path = repo["checkout"]
    result = _manage(repo)

    assert result["ok"] is True
    assert result["pushed"] is True
    assert result["commit_id"] == _git(checkout, "rev-parse", "HEAD").stdout.strip()
    assert _git(checkout, "show", "HEAD:sase/sase.yml").stdout.endswith(
        "is_sase_managed: true\n"
    )
    assert _git(
        checkout, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).stdout.splitlines() == ["sase/sase.yml"]
    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    assert journal["management"]["marker_write_stage"] == "written"
    assert journal["management"]["baseline_config_hash"]
    assert journal["management"]["expected_config_hash"]
    assert journal["management"]["commit_parent"]
    assert journal["management"]["commit_content_hash"]
    assert journal["management"]["commit_id"] == result["commit_id"]
    assert journal["management"]["push_verified"] is True
    assert journal["management"]["push_expected_oid"] == result["commit_id"]


def test_unrelated_staged_file_stays_out_of_marker_commit(
    onboarding_repo: dict[str, Any],
) -> None:
    repo = onboarding_repo
    checkout: Path = repo["checkout"]
    (checkout / "notes.txt").write_text("keep staged\n", encoding="utf-8")
    _git(checkout, "add", "notes.txt")

    result = _manage(repo)

    assert _git(
        checkout,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        result["commit_id"],
    ).stdout.splitlines() == ["sase/sase.yml"]
    assert _git(checkout, "diff", "--cached", "--name-only").stdout.splitlines() == [
        "notes.txt"
    ]


@pytest.mark.parametrize("failed_command", ["add", "commit"])
def test_add_and_commit_failures_leave_recoverable_marker(
    onboarding_repo: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failed_command: str,
) -> None:
    repo = onboarding_repo
    real_run_git = manage._run_git

    def fail_once(
        checkout: Path,
        *args: str,
        timeout: float = manage._GIT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == failed_command:
            return subprocess.CompletedProcess(
                ["git", *args], 1, "", "injected failure"
            )
        return real_run_git(checkout, *args, timeout=timeout)

    monkeypatch.setattr(manage, "_run_git", fail_once)
    with pytest.raises(manage.ManagementError, match="injected failure"):
        _manage(repo)

    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    assert journal["management"]["expected_config_hash"]
    assert (
        _git(repo["checkout"], "rev-parse", "HEAD").stdout.strip()
        == _git(repo["bare"], "rev-parse", "refs/heads/main").stdout.strip()
    )


def test_push_rejection_can_retry_without_duplicate_commit(
    onboarding_repo: dict[str, Any],
) -> None:
    repo = onboarding_repo
    hook = repo["bare"] / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\necho rejected by test hook >&2\nexit 1\n", encoding="utf-8"
    )
    hook.chmod(0o755)

    with pytest.raises(manage.ManagementError, match="protected default branch"):
        _manage(repo)

    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    marker_commit = journal["management"]["commit_id"]
    assert marker_commit
    assert journal["management"]["push_verified"] is False
    assert _git(repo["checkout"], "rev-list", "--count", "HEAD").stdout.strip() == "2"

    set_journal_status(_IDENTITY, "failed", display="sase-org/bob")
    hook.unlink()
    result = _manage(repo)

    assert result["commit_id"] == marker_commit
    assert _git(repo["checkout"], "rev-list", "--count", "HEAD").stdout.strip() == "2"
    assert (
        _git(repo["bare"], "rev-parse", "refs/heads/main").stdout.strip()
        == marker_commit
    )


def test_lost_responses_after_write_commit_and_push_are_reobserved(
    onboarding_repo: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_enable = manage.enable_sase_management
    real_run_git = manage._run_git

    def lost_write_response(path: Path) -> Any:
        result = real_enable(path)
        return SimpleNamespace(changed=result.changed, error="simulated lost response")

    def lost_git_response(
        checkout: Path,
        *args: str,
        timeout: float = manage._GIT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        result = real_run_git(checkout, *args, timeout=timeout)
        if args and args[0] in {"commit", "push"} and result.returncode == 0:
            return subprocess.CompletedProcess(
                result.args,
                1,
                result.stdout,
                "simulated lost response after effect",
            )
        return result

    monkeypatch.setattr(manage, "enable_sase_management", lost_write_response)
    monkeypatch.setattr(manage, "_run_git", lost_git_response)

    result = _manage(onboarding_repo)

    assert result["pushed"] is True
    assert (
        _git(onboarding_repo["checkout"], "rev-list", "--count", "HEAD").stdout.strip()
        == "2"
    )
    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    assert journal["management"]["push_verified"] is True


def test_already_managed_repo_does_not_create_duplicate_commit(
    onboarding_repo: dict[str, Any],
) -> None:
    repo = onboarding_repo
    checkout: Path = repo["checkout"]
    config = checkout / "sase" / "sase.yml"
    config.write_text(
        config.read_text(encoding="utf-8") + "is_sase_managed: true\n",
        encoding="utf-8",
    )
    _git(checkout, "add", "sase/sase.yml")
    _git(checkout, "commit", "-m", "already managed")
    _git(checkout, "push", "origin", "main")
    repo["remote"]["sase_managed"] = True
    initial_head = _git(checkout, "rev-parse", "HEAD").stdout.strip()

    result = _manage(repo)

    assert result["changed"] is False
    assert _git(checkout, "rev-parse", "HEAD").stdout.strip() == initial_head
    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    assert journal["management"]["push_verified"] is True


@pytest.fixture
def empty_origin_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    bare = tmp_path / "origin.git"
    checkout = tmp_path / "checkout"
    bare.mkdir()
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(bare))
    _git(tmp_path, "clone", str(bare), str(checkout))
    _git(checkout, "config", "user.name", "Onboarding Test")
    _git(checkout, "config", "user.email", "onboarding@example.test")
    monkeypatch.setattr(
        manage.workspace_provider,
        "parse_repo_ref",
        lambda workflow, ref: SimpleNamespace(identity_key=_IDENTITY),
    )
    target = {
        "workflow_type": "gh",
        "identity_key": _IDENTITY,
        "ref": "sase-org/bob",
        "display": "sase-org/bob",
        "checkout_dir": str(checkout),
    }
    remote = {
        "default_branch": "",
        "is_empty": True,
        "can_push": True,
        "sase_managed": False,
    }
    record_intent(
        identity_key=_IDENTITY,
        ref="sase-org/bob",
        display="sase-org/bob",
        workflow_type="gh",
        mode="add",
        intent_fingerprint=_FINGERPRINT,
        setup_required=True,
    )
    return {
        "bare": bare,
        "checkout": checkout,
        "target": target,
        "remote": remote,
        "tmp_path": tmp_path,
    }


def _origin_heads(bare: Path) -> dict[str, str]:
    result = _git(bare, "show-ref", "--heads", check=False)
    if result.returncode not in {0, 1}:
        raise AssertionError(result.stderr or result.stdout)
    heads: dict[str, str] = {}
    for line in result.stdout.splitlines():
        oid, ref = line.split()
        heads[ref] = oid
    return heads


def test_empty_origin_creates_root_marker_and_leaves_readme_uncommitted(
    empty_origin_repo: dict[str, Any],
) -> None:
    repo = empty_origin_repo
    checkout: Path = repo["checkout"]
    (checkout / "README.md").write_text("keep me untracked\n", encoding="utf-8")

    result = _manage(repo)

    assert result["ok"] is True
    assert result["pushed"] is True
    commit_id = result["commit_id"]
    heads = _origin_heads(repo["bare"])
    assert list(heads) == ["refs/heads/main"]
    assert heads["refs/heads/main"] == commit_id
    assert _git(checkout, "rev-list", "--count", commit_id).stdout.strip() == "1"
    assert _git(
        checkout,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit_id,
    ).stdout.splitlines() == ["sase/sase.yml"]
    assert _git(checkout, "show", f"{commit_id}:sase/sase.yml").stdout.endswith(
        "is_sase_managed: true\n"
    )
    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    assert journal["management"]["push_verified"] is True
    assert journal["management"]["root_commit"] is True
    assert journal["management"]["commit_branch"] == "main"
    assert journal["management"]["commit_parent"] == ""
    status = _git(checkout, "status", "--porcelain", "--untracked-files=all").stdout
    assert "README.md" in status
    assert _git(
        checkout, "ls-tree", "-r", "--name-only", commit_id
    ).stdout.splitlines() == ["sase/sase.yml"]


def test_empty_origin_retargets_unborn_head_to_provider_branch(
    empty_origin_repo: dict[str, Any],
) -> None:
    repo = empty_origin_repo
    checkout: Path = repo["checkout"]
    repo["remote"]["default_branch"] = "develop"

    result = _manage(repo)

    assert _git(checkout, "symbolic-ref", "--short", "HEAD").stdout.strip() == "develop"
    assert (
        _git(checkout, "config", "--get", "branch.develop.remote").stdout.strip()
        == "origin"
    )
    assert (
        _git(checkout, "config", "--get", "branch.develop.merge").stdout.strip()
        == "refs/heads/develop"
    )
    heads = _origin_heads(repo["bare"])
    assert heads == {"refs/heads/develop": result["commit_id"]}


def test_empty_origin_push_failure_retries_same_commit(
    empty_origin_repo: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = empty_origin_repo
    real_run_git = manage._run_git
    failed = {"once": False}

    def fail_push_once(
        checkout: Path,
        *args: str,
        timeout: float = manage._GIT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "push" and not failed["once"]:
            failed["once"] = True
            return subprocess.CompletedProcess(
                ["git", *args], 1, "", "injected push failure"
            )
        return real_run_git(checkout, *args, timeout=timeout)

    monkeypatch.setattr(manage, "_run_git", fail_push_once)
    with pytest.raises(manage.ManagementError, match="injected push failure"):
        _manage(repo)

    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    marker_commit = journal["management"]["commit_id"]
    assert marker_commit
    assert _origin_heads(repo["bare"]) == {}

    set_journal_status(_IDENTITY, "failed", display="sase-org/bob")
    monkeypatch.setattr(manage, "_run_git", real_run_git)
    result = _manage(repo)

    assert result["commit_id"] == marker_commit
    assert _git(repo["checkout"], "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert _origin_heads(repo["bare"]) == {"refs/heads/main": marker_commit}


def test_empty_origin_recovers_when_push_evidence_is_lost(
    empty_origin_repo: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = empty_origin_repo
    real_run_git = manage._run_git

    def crash_after_push(
        checkout: Path,
        *args: str,
        timeout: float = manage._GIT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        result = real_run_git(checkout, *args, timeout=timeout)
        if args and args[0] == "push" and result.returncode == 0:
            raise manage.ManagementError("simulated crash after push")
        return result

    monkeypatch.setattr(manage, "_run_git", crash_after_push)
    with pytest.raises(manage.ManagementError, match="simulated crash after push"):
        _manage(repo)

    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    marker_commit = journal["management"]["commit_id"]
    assert marker_commit
    assert _origin_heads(repo["bare"]) == {"refs/heads/main": marker_commit}
    assert journal["management"].get("push_verified") is not True

    set_journal_status(_IDENTITY, "failed", display="sase-org/bob")
    monkeypatch.setattr(manage, "_run_git", real_run_git)
    result = _manage(repo)

    assert result["ok"] is True
    assert result["commit_id"] == marker_commit
    journal = lookup_journal(_IDENTITY)
    assert journal is not None
    assert journal["management"]["push_verified"] is True


def test_empty_origin_fails_closed_when_origin_gains_a_commit(
    empty_origin_repo: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = empty_origin_repo
    checkout: Path = repo["checkout"]
    tmp_path: Path = repo["tmp_path"]
    real_run_git = manage._run_git

    def seed_origin_after_marker_commit(
        path: Path,
        *args: str,
        timeout: float = manage._GIT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        result = real_run_git(path, *args, timeout=timeout)
        if args and args[0] == "commit" and result.returncode == 0:
            second = tmp_path / "second"
            if not second.exists():
                _git(tmp_path, "clone", str(repo["bare"]), str(second))
                _git(second, "config", "user.name", "Onboarding Test")
                _git(second, "config", "user.email", "onboarding@example.test")
                (second / "notes.txt").write_text("foreign\n", encoding="utf-8")
                _git(second, "add", "notes.txt")
                _git(second, "commit", "-m", "foreign root")
                _git(second, "push", "origin", "HEAD:refs/heads/main")
        return result

    monkeypatch.setattr(manage, "_run_git", seed_origin_after_marker_commit)
    with pytest.raises(manage.ManagementError, match="origin received commits"):
        _manage(repo)

    heads = _origin_heads(repo["bare"])
    assert list(heads) == ["refs/heads/main"]
    foreign = heads["refs/heads/main"]
    local = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    assert local != foreign
    assert _git(checkout, "log", "-1", "--format=%s").stdout.strip() == (
        "chore: mark repository as SASE-managed"
    )
    assert (
        _git(repo["bare"], "log", "-1", "--format=%s", "refs/heads/main").stdout.strip()
        == "foreign root"
    )


def test_empty_origin_rejects_unrelated_local_commits(
    empty_origin_repo: dict[str, Any],
) -> None:
    repo = empty_origin_repo
    checkout: Path = repo["checkout"]
    (checkout / "notes.txt").write_text("local\n", encoding="utf-8")
    _git(checkout, "add", "notes.txt")
    _git(checkout, "commit", "-m", "unrelated")

    with pytest.raises(manage.ManagementError, match="already has local commits"):
        _manage(repo)

    assert _origin_heads(repo["bare"]) == {}


def test_nonempty_origin_with_empty_default_branch_still_errors(
    onboarding_repo: dict[str, Any],
) -> None:
    repo = onboarding_repo
    repo["remote"]["default_branch"] = ""
    repo["remote"]["is_empty"] = False

    with pytest.raises(
        manage.ManagementError,
        match="the provider did not report a usable default branch",
    ):
        _manage(repo)
