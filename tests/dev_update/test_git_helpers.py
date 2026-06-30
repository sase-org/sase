"""Tests for dev-update git helper primitives."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.version import _git


def test_probe_git_metadata_at_ref_uses_requested_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_run_git(root: Path, *args: str, **_kwargs: object) -> str:
        calls.append((root, args))
        if args == ("rev-parse", "--show-toplevel"):
            return "/repo"
        if args == ("rev-parse", "origin/main"):
            return "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        if args == ("rev-parse", "--short=9", "origin/main"):
            return "bbbbbbbbb"
        if args == (
            "describe",
            "--tags",
            "--match",
            "v[0-9]*",
            "--abbrev=0",
            "origin/main",
        ):
            return "v0.5.0"
        if args == ("rev-list", "--count", "v0.5.0..origin/main"):
            return "4"
        raise AssertionError(args)

    monkeypatch.setattr(_git, "run_git", fake_run_git)

    result = _git.probe_git_metadata_at_ref(Path("/repo/pkg"), "origin/main")

    assert result.warning is None
    assert result.metadata is not None
    assert result.metadata.root == "/repo"
    assert result.metadata.short_commit == "bbbbbbbbb"
    assert result.metadata.tag == "v0.5.0"
    assert result.metadata.distance == 4
    assert result.metadata.dirty is False
    assert (Path("/repo"), ("status", "--porcelain")) not in calls


def test_classify_git_upstream_resolves_branch_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_git(root: Path, *args: str, **_kwargs: object) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return "/repo"
        if args == ("status", "--porcelain"):
            return ""
        if args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            return "main"
        if args == (
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ):
            return "origin/main"
        if args == ("config", "--get", "branch.main.remote"):
            return "origin"
        if args == ("config", "--get", "branch.main.merge"):
            return "refs/heads/main"
        if args == ("rev-list", "--left-right", "--count", "HEAD...origin/main"):
            return "0 2"
        raise AssertionError(args)

    monkeypatch.setattr(_git, "run_git", fake_run_git)

    status = _git.classify_git_upstream(Path("/repo"))

    assert status.root == "/repo"
    assert status.upstream == "origin/main"
    assert status.remote == "origin"
    assert status.remote_branch == "main"
    assert status.detached is False
    assert status.dirty is False
    assert status.ahead == 0
    assert status.behind == 2
    assert status.strictly_behind is True


def test_classify_git_upstream_handles_detached_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_git(root: Path, *args: str, **_kwargs: object) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return "/repo"
        if args == ("status", "--porcelain"):
            return ""
        if args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            raise subprocess.CalledProcessError(1, ["git"])
        raise AssertionError(args)

    monkeypatch.setattr(_git, "run_git", fake_run_git)

    status = _git.classify_git_upstream(Path("/repo"))

    assert status.detached is True
    assert status.upstream is None
    assert status.ahead is None
    assert status.behind is None


def test_fetch_and_merge_git_ops_use_resolved_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, tuple[str, ...], float | None]] = []

    def fake_run_git(
        root: Path, *args: str, timeout: float | None = None, **_kwargs: object
    ) -> str:
        calls.append((root, args, timeout))
        return ""

    monkeypatch.setattr(_git, "run_git", fake_run_git)
    status = _git.GitUpstreamStatus(
        root="/repo",
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        detached=False,
        dirty=False,
        ahead=0,
        behind=1,
    )

    _git.fetch_git_upstream(status)
    _git.merge_git_ff_only(Path("/repo"), "origin/main")

    assert calls[0][0] == Path("/repo")
    assert calls[0][1] == (
        "fetch",
        "--quiet",
        "--tags",
        "--force",
        "origin",
        "main",
    )
    assert calls[1][1] == ("merge", "--ff-only", "origin/main")


def test_fetch_git_upstream_fetches_tags_without_tracking_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, tuple[str, ...], float | None]] = []

    def fake_run_git(
        root: Path, *args: str, timeout: float | None = None, **_kwargs: object
    ) -> str:
        calls.append((root, args, timeout))
        return ""

    monkeypatch.setattr(_git, "run_git", fake_run_git)
    status = _git.GitUpstreamStatus(
        root="/repo",
        upstream="origin/main",
        remote="origin",
        remote_branch=None,
        detached=False,
        dirty=False,
        ahead=0,
        behind=1,
    )

    _git.fetch_git_upstream(status)

    assert calls == [
        (
            Path("/repo"),
            ("fetch", "--quiet", "--tags", "--force", "origin"),
            _git._GIT_MUTATE_TIMEOUT_SECONDS,
        )
    ]
