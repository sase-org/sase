"""Coverage for read-only git status helpers avoiding index.lock contention."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.llm_provider.commit_finalizer_git_status import (
    git_changed_files,
    git_status_records,
    split_pre_existing_changed_files,
)


def _fake_run(
    captured: list[list[str]],
) -> object:
    def fake_run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        captured.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    return fake_run


def test_git_changed_files_passes_no_optional_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))

    git_changed_files(str(tmp_path))

    assert len(captured) == 1
    args = captured[0]
    assert args[:4] == ["git", "--no-optional-locks", "-C", str(tmp_path)]
    assert args[4] == "status"


def test_git_status_records_passes_no_optional_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))

    git_status_records(str(tmp_path))

    assert len(captured) == 1
    args = captured[0]
    assert args[:4] == ["git", "--no-optional-locks", "-C", str(tmp_path)]
    assert args[4] == "status"


def test_git_status_records_uses_settle_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    git_status_records(str(tmp_path))

    assert captured == [10]


def test_split_pre_existing_matches_untracked_directory_listing(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "SASE Test"],
        cwd=repo,
        check=True,
    )
    scratch = repo / ".sase-v2-stage-abc"
    scratch.mkdir()
    (scratch / "payload.json").write_text("{}\n", encoding="utf-8")

    still, pre_existing = split_pre_existing_changed_files(
        str(repo),
        [".sase-v2-stage-abc/payload.json"],
        {".sase-v2-stage-abc/": ("??", None)},
    )
    assert still == []
    assert pre_existing == [".sase-v2-stage-abc/payload.json"]
