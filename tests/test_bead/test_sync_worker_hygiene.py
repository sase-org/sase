"""Tests for managed sync worker hygiene: cooldown, env, redaction, logs."""

from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace

from sase.bead.sync import _new_sync_log_path
from sase.bead.sync_worker import run_managed_sync_worker
from sase.sdd._repository_recovery_markers import FAILED_INTEGRATION_MARKER
from sase.sdd._repository_types import (
    SddIntegrationOutcome,
    SddIntegrationStatus,
)

from .sync_test_helpers import init_git_repo


def _successful_integration() -> SimpleNamespace:
    return SimpleNamespace(
        succeeded=True,
        status=SimpleNamespace(value="integrated"),
        integrated=True,
        restored=False,
        resolved_files=(),
        error=None,
        upstream_present=True,
    )


def _fake_git_factory(pushed: subprocess.CompletedProcess[str]):
    """Build a ``sync_worker._git`` stand-in that only answers real call sites."""

    def fake_git(repo_root, args, *, op, network=False):
        del network
        if args[:2] == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                returncode=0,
                stdout=str(repo_root / ".git") + "\n",
                stderr="",
            )
        if args == ["push"]:
            return pushed
        raise AssertionError(f"unexpected git call for op {op}: {args}")

    return fake_git


def _stub_successful_integration(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        lambda *_args, **_kwargs: _successful_integration(),
    )


def test_managed_sync_worker_clears_failed_integration_marker(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    marker = tmp_path / ".git" / FAILED_INTEGRATION_MARKER
    marker.write_text(
        json.dumps({"clone_path": str(tmp_path), "timestamp": 0.0}),
        encoding="utf-8",
    )
    _stub_successful_integration(monkeypatch)
    monkeypatch.setattr(
        "sase.bead.sync_worker._git",
        _fake_git_factory(
            subprocess.CompletedProcess(
                ["git", "push"], returncode=0, stdout="", stderr=""
            )
        ),
    )

    outcome = run_managed_sync_worker(
        tmp_path,
        beads_dir,
        log_path=tmp_path / "sync.log",
    )

    assert outcome.pushed is True
    assert not marker.exists()


def test_managed_sync_worker_does_not_mutate_process_environment(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
    _stub_successful_integration(monkeypatch)
    observed_envs: list[dict[str, str] | None] = []

    def fake_run_sdd_git_write(args, *, cwd, op, env=None, **_kwargs):
        del cwd, op
        observed_envs.append(dict(env) if env is not None else None)
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=0,
            stdout=".git\n",
            stderr="",
        )

    monkeypatch.setattr(
        "sase.sdd._git_contention.run_sdd_git_write",
        fake_run_sdd_git_write,
    )

    outcome = run_managed_sync_worker(
        tmp_path,
        beads_dir,
        log_path=tmp_path / "sync.log",
    )

    assert outcome.pushed is True
    assert "GIT_TERMINAL_PROMPT" not in os.environ
    assert observed_envs
    assert all(env is not None for env in observed_envs)
    assert all(env["GIT_TERMINAL_PROMPT"] == "0" for env in observed_envs if env)


def test_managed_sync_worker_redacts_credentials_in_push_errors(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    _stub_successful_integration(monkeypatch)
    log_path = tmp_path / "sync.log"
    monkeypatch.setattr(
        "sase.bead.sync_worker._git",
        _fake_git_factory(
            subprocess.CompletedProcess(
                ["git", "push"],
                returncode=128,
                stdout="",
                stderr=(
                    "fatal: could not read from "
                    "https://someone:ghp_secrettoken@example.test/plans.git"
                ),
            )
        ),
    )

    outcome = run_managed_sync_worker(tmp_path, beads_dir, log_path=log_path)

    assert outcome.pushed is False
    assert outcome.error is not None
    assert "ghp_secrettoken" not in outcome.error
    assert "https://<redacted>@example.test/plans.git" in outcome.error
    log_text = log_path.read_text(encoding="utf-8")
    assert "ghp_secrettoken" not in log_text


def test_managed_sync_worker_reintegrates_after_push_race(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    integrations: list[int] = []

    def integrate(*_args, **_kwargs):
        integrations.append(len(integrations) + 1)
        return SddIntegrationOutcome(
            SddIntegrationStatus.SUCCESS,
            integrated=bool(len(integrations) > 1),
            upstream_present=True,
        )

    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        integrate,
    )
    pushes = iter(
        [
            subprocess.CompletedProcess(
                ["git", "push"],
                returncode=1,
                stdout="",
                stderr=(
                    "! [rejected] main -> main (fetch first)\n"
                    "error: failed to push some refs"
                ),
            ),
            subprocess.CompletedProcess(
                ["git", "push"], returncode=0, stdout="", stderr=""
            ),
        ]
    )

    def fake_git(repo_root, args, *, op, network=False):
        del op, network
        if args[:2] == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                returncode=0,
                stdout=str(repo_root / ".git") + "\n",
                stderr="",
            )
        if args == ["push"]:
            return next(pushes)
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr("sase.bead.sync_worker._git", fake_git)
    log_path = tmp_path / "sync.log"

    outcome = run_managed_sync_worker(tmp_path, beads_dir, log_path=log_path)

    assert outcome.pushed is True
    assert outcome.integrated is True
    assert integrations == [1, 2]
    events = [
        json.loads(line)["event"]
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("push_rejected_retry") == 1


def test_managed_sync_worker_bounds_rejected_push_retries(tmp_path, monkeypatch):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    integration_count = 0

    def integrate(*_args, **_kwargs):
        nonlocal integration_count
        integration_count += 1
        return SddIntegrationOutcome(
            SddIntegrationStatus.SUCCESS,
            upstream_present=True,
        )

    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        integrate,
    )

    def fake_git(repo_root, args, *, op, network=False):
        del op, network
        if args[:2] == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                returncode=0,
                stdout=str(repo_root / ".git") + "\n",
                stderr="",
            )
        if args == ["push"]:
            return subprocess.CompletedProcess(
                ["git", "push"],
                returncode=1,
                stdout="",
                stderr="[rejected] (non-fast-forward)\nfailed to push some refs",
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr("sase.bead.sync_worker._git", fake_git)

    outcome = run_managed_sync_worker(
        tmp_path,
        beads_dir,
        log_path=tmp_path / "sync.log",
    )

    assert outcome.pushed is False
    assert outcome.error is not None
    assert "rejected after 3 attempts" in outcome.error
    assert integration_count == 3


def test_managed_sync_worker_retries_only_transient_local_changes(
    tmp_path, monkeypatch
):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    outcomes = iter(
        [
            SddIntegrationOutcome(
                SddIntegrationStatus.LOCAL_CHANGES,
                upstream_present=True,
                error="tracked worktree changes",
            ),
            SddIntegrationOutcome(
                SddIntegrationStatus.SUCCESS,
                upstream_present=True,
            ),
        ]
    )
    monkeypatch.setattr(
        "sase.sdd._repository_transaction.integrate_sdd_repository",
        lambda *_args, **_kwargs: next(outcomes),
    )
    monkeypatch.setattr("sase.bead.sync_worker.time.sleep", lambda _delay: None)
    monkeypatch.setattr(
        "sase.bead.sync_worker._git",
        _fake_git_factory(
            subprocess.CompletedProcess(
                ["git", "push"], returncode=0, stdout="", stderr=""
            )
        ),
    )
    log_path = tmp_path / "sync.log"

    outcome = run_managed_sync_worker(tmp_path, beads_dir, log_path=log_path)

    assert outcome.pushed is True
    events = [
        json.loads(line)["event"]
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("local_changes_retry") == 1


def test_new_sync_log_paths_are_unique_within_one_second(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sase.core.paths.ensure_sase_directory",
        lambda _name: str(tmp_path),
    )
    monkeypatch.setattr("sase.core.time.generate_timestamp", lambda: "20260726120000")

    first = _new_sync_log_path()
    second = _new_sync_log_path()

    assert first != second
    assert first.parent == second.parent == tmp_path
    assert first.name.startswith("sync-20260726120000-")
    assert second.name.startswith("sync-20260726120000-")
