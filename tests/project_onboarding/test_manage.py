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


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
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
        check=True,
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
