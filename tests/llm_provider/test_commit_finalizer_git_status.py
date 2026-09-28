"""Coverage for read-only git status helpers avoiding index.lock contention."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.llm_provider.commit_finalizer_git_status import (
    git_changed_files,
    git_status_records,
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
