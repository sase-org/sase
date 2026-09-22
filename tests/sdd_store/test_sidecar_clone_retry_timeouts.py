"""Timeout, deadline, checkout, and reference-fallback retries for sidecar clones."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.sdd._store_clone_ops import clone_sdd_store
from sase.sdd._store_types import SddMaterializationError

from ._clone_retry_helpers import (
    fake_clone_retryability,
    normalized_clone_calls,
    stage_clone_path,
    write_partial_clone,
    write_valid_clone,
)


@pytest.fixture(autouse=True)
def _fake_clone_retryability(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clone_retryability(monkeypatch)


def test_sidecar_clone_timeout_retries_without_reference_and_cleans_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_then_success(args: list[str], **_kwargs):
        calls.append(list(args))
        if len(calls) == 1:
            write_partial_clone(args)
            raise SddGitCommandTimeout("injected timeout")
        assert not stage_clone_path(calls[0]).exists()
        write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_remote._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_then_success)

    assert (
        clone_sdd_store(
            remote,
            clone_dir,
            reference_repo=reference,
            strict=True,
        )
        is True
    )

    assert normalized_clone_calls(calls, clone_dir) == [
        [
            "clone",
            "--reference-if-able",
            str(reference),
            "--dissociate",
            remote,
            str(clone_dir),
        ],
        ["clone", remote, str(clone_dir)],
    ]


def test_sidecar_clone_timeout_retries_with_no_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    sleeps: list[float] = []
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_then_success(args: list[str], **_kwargs):
        calls.append(list(args))
        if len(calls) == 1:
            write_partial_clone(args)
            raise SddGitCommandTimeout("injected timeout")
        assert not stage_clone_path(calls[0]).exists()
        write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_then_success)
    monkeypatch.setattr("sase.sdd._store_clone_common.time.sleep", lambda _delay: None)
    monkeypatch.setattr(
        "sase.sdd._store_clone_remote.sleep_before_retry",
        lambda delay, _deadline: sleeps.append(delay) or True,
    )

    assert clone_sdd_store(remote, clone_dir, strict=True) is True

    assert normalized_clone_calls(calls, clone_dir) == [
        ["clone", remote, str(clone_dir)],
        ["clone", remote, str(clone_dir)],
    ]
    assert sleeps == [0.25]


def test_sidecar_clone_timeout_budget_escalates_across_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    timeouts: list[float] = []
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_twice_then_success(args: list[str], timeout: float, **_kwargs):
        timeouts.append(timeout)
        if len(timeouts) < 3:
            write_partial_clone(args)
            raise SddGitCommandTimeout("injected timeout")
        write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.network_git_timeout", lambda: 120.0)
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_twice_then_success)
    monkeypatch.setattr("sase.sdd._store_clone_common.time.sleep", lambda _delay: None)

    assert clone_sdd_store(remote, clone_dir, strict=True) is True

    assert timeouts == [120.0, 180.0, 240.0]


def test_sidecar_clone_timeout_retry_honors_deadline_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    now = [100.0]
    calls = 0
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_clone(args: list[str], **_kwargs):
        nonlocal calls
        calls += 1
        write_partial_clone(args)
        now[0] = 105.0
        raise SddGitCommandTimeout("injected timeout")

    monkeypatch.setattr("sase.sdd._commit.network_git_timeout", lambda: 120.0)
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_clone)
    monkeypatch.setattr("sase.sdd._store_clone_common.time.monotonic", lambda: now[0])
    monkeypatch.setattr("sase.sdd._store_clone_common.time.sleep", lambda _delay: None)

    with pytest.raises(
        SddMaterializationError,
        match="deadline expired before retrying SDD clone",
    ):
        clone_sdd_store(
            remote,
            clone_dir,
            strict=True,
            deadline=105.0,
        )

    assert calls == 1
    assert not clone_dir.exists()


@pytest.mark.parametrize("strict", [False, True])
def test_sidecar_clone_timeout_reference_fallback_then_retry_schedule_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    from sase.sdd._commit import SddGitCommandTimeout

    def timeout_clone(args: list[str], **_kwargs):
        calls.append(list(args))
        write_partial_clone(args)
        raise SddGitCommandTimeout("injected timeout")

    monkeypatch.setattr(
        "sase.sdd._store_clone_remote._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", timeout_clone)
    monkeypatch.setattr("sase.sdd._store_clone_common.time.sleep", lambda _delay: None)

    if strict:
        with pytest.raises(
            SddMaterializationError,
            match="timed out cloning SDD store",
        ):
            clone_sdd_store(
                remote,
                clone_dir,
                reference_repo=reference,
                strict=True,
            )
    else:
        assert (
            clone_sdd_store(
                remote,
                clone_dir,
                reference_repo=reference,
                strict=False,
            )
            is False
        )

    assert normalized_clone_calls(calls, clone_dir) == [
        [
            "clone",
            "--reference-if-able",
            str(reference),
            "--dissociate",
            remote,
            str(clone_dir),
        ],
        ["clone", remote, str(clone_dir)],
        ["clone", remote, str(clone_dir)],
        ["clone", remote, str(clone_dir)],
    ]
    assert not clone_dir.exists()


def test_sidecar_clone_checkout_failure_retries_without_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def checkout_failure_then_success(args: list[str], **_kwargs):
        calls.append(list(args))
        if len(calls) == 1:
            write_partial_clone(args)
            return subprocess.CompletedProcess(
                args=["git", "clone"],
                returncode=128,
                stdout="",
                stderr=(
                    "fatal: unable to parse commit "
                    "8c09ae950bbf8201016911d1c9c90726b426e11b\n"
                    "warning: Clone succeeded, but checkout failed."
                ),
            )
        assert not stage_clone_path(calls[0]).exists()
        write_valid_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_remote._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", checkout_failure_then_success)
    monkeypatch.setattr("sase.sdd._store_clone_common.time.sleep", lambda _delay: None)
    monkeypatch.setattr(
        "sase.sdd._store_clone_remote.sleep_before_retry",
        lambda delay, _deadline: sleeps.append(delay) or True,
    )

    assert (
        clone_sdd_store(
            remote,
            clone_dir,
            reference_repo=reference,
            strict=True,
        )
        is True
    )

    assert "--reference-if-able" in calls[0]
    assert "--reference-if-able" not in calls[1]
    assert sleeps == []


def test_sidecar_clone_reference_fallback_is_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    reference = tmp_path / "primary" / "sase" / "repos" / "plans"
    calls: list[list[str]] = []
    diagnostic = (
        "fatal: unable to parse commit "
        "8c09ae950bbf8201016911d1c9c90726b426e11b\n"
        "warning: Clone succeeded, but checkout failed."
    )

    def always_fail(args: list[str], **_kwargs):
        calls.append(list(args))
        write_partial_clone(args)
        return subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr=diagnostic,
        )

    monkeypatch.setattr(
        "sase.sdd._store_clone_remote._matching_clone_reference",
        lambda _reference_repo, _remote_url: reference,
    )
    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", always_fail)

    with pytest.raises(SddMaterializationError, match="unable to parse commit"):
        clone_sdd_store(
            remote,
            clone_dir,
            reference_repo=reference,
            strict=True,
        )

    assert normalized_clone_calls(calls, clone_dir) == [
        [
            "clone",
            "--reference-if-able",
            str(reference),
            "--dissociate",
            remote,
            str(clone_dir),
        ],
        ["clone", remote, str(clone_dir)],
    ]
    assert not clone_dir.exists()
