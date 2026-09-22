"""Failure cleanup, transient retries, and attempt telemetry for sidecar clones."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.sdd._git import run_sdd_git
from sase.sdd._store_clone_ops import clone_sdd_store
from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_types import SddMaterializationError

from ._clone_retry_helpers import (
    fake_clone_retryability,
    write_partial_clone,
    write_valid_clone,
)


@pytest.fixture(autouse=True)
def _fake_clone_retryability(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clone_retryability(monkeypatch)


def test_run_sdd_git_records_margin_and_supplied_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, object]] = []
    monkeypatch.setattr("sase.logs.log_tui_git_operation", records.append)

    run_sdd_git(
        ["--version"],
        cwd=tmp_path,
        op="sdd.clone.remote",
        timeout=10.0,
        check=True,
        capture_output=True,
        text=True,
        always_log=True,
        telemetry={
            "retry_attempt_index": 2,
            "retry_attempts_total": 4,
            "reference_repo_used": False,
            "sdd_store_name": "plans",
        },
    )

    assert len(records) == 1
    record = records[0]
    assert record["retry_attempt_index"] == 2
    assert record["retry_attempts_total"] == 4
    assert record["reference_repo_used"] is False
    assert record["sdd_store_name"] == "plans"
    assert record["duration_limit_ratio"] >= 0
    assert record["duration_limit_margin_ms"] <= 10_000.0


def test_sidecar_clone_failure_removes_partial_target_and_surfaces_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    attempts = 0

    def failed_clone(args: list[str], **_kwargs):
        nonlocal attempts
        attempts += 1
        write_partial_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="authentication failed for plans remote",
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", failed_clone)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store_from_primary",
        lambda *_args: pytest.fail("clone failure used a local fallback"),
    )

    with pytest.raises(
        SddMaterializationError, match="authentication failed for plans remote"
    ):
        ensure_sidecar_sdd_clone(clone_dir, remote, strict=True)

    assert not clone_dir.exists()
    assert attempts == 1


def test_sidecar_clone_retries_transient_transport_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    attempts = 0
    sleeps: list[float] = []

    def flaky_clone(args: list[str], **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            write_partial_clone(args)
            return subprocess.CompletedProcess(
                args=["git", "clone"],
                returncode=128,
                stdout="",
                stderr=(
                    "Connection to ssh.example.test closed by remote host.\n"
                    "fetch-pack: unexpected disconnect while reading sideband packet\n"
                    "fatal: early EOF\n"
                    "fatal: fetch-pack: invalid index-pack output"
                ),
            )
        write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", flaky_clone)
    monkeypatch.setattr("sase.sdd._store_clone_common.time.sleep", lambda _delay: None)
    monkeypatch.setattr(
        "sase.sdd._store_clone_remote.sleep_before_retry",
        lambda delay, _deadline: sleeps.append(delay) or True,
    )

    ensure_sidecar_sdd_clone(clone_dir, remote, strict=True)

    assert attempts == 3
    assert sleeps == [0.25, 1.0]
    assert not (clone_dir / "partial").exists()


def test_sidecar_clone_passes_attempt_telemetry_to_git_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    telemetry: list[dict[str, object]] = []

    def fail_then_success(args: list[str], **kwargs):
        telemetry.append(dict(kwargs["telemetry"]))
        if len(telemetry) == 1:
            write_partial_clone(args)
            return subprocess.CompletedProcess(
                args=["git", "clone"],
                returncode=128,
                stdout="",
                stderr="fatal: early EOF",
            )
        write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_remote._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", fail_then_success)
    monkeypatch.setattr("sase.sdd._store_clone_common.time.sleep", lambda _delay: None)

    assert clone_sdd_store(remote, clone_dir, reference_repo=reference, strict=True)

    assert telemetry[0]["retry_attempt_index"] == 0
    assert telemetry[0]["retry_attempts_total"] == 4
    assert telemetry[0]["reference_repo_used"] is True
    assert telemetry[0]["sdd_store_name"] == "plans"
    assert Path(str(telemetry[0]["sdd_clone_stage_path"])).name == "clone"
    assert telemetry[1]["retry_attempt_index"] == 1
    assert telemetry[1]["reference_repo_used"] is False
