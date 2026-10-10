"""Tests for W4 probe module mapping and quiescence code-change times."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.auto_restart.managed_roots import ManagedRoot
from sase.agent.auto_restart.probe import probe_modules_for_frames
from sase.agent.auto_restart.quiescence import check_quiescence


GIT_AVAILABLE = shutil.which("git") is not None


def _root(
    source_root: Path,
    *,
    name: str = "sase",
    role: str = "host",
) -> ManagedRoot:
    return ManagedRoot(
        name=name,
        role=role,
        source_root=str(source_root),
        commit="abc1234",
        version="0.0.0",
        install_type="editable",
    )


def test_probe_modules_src_layout_editable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "sase"
    frame = checkout / "src" / "sase" / "axe" / "x.py"
    frame.parent.mkdir(parents=True)
    (checkout / "src" / "sase" / "__init__.py").write_text("", encoding="utf-8")
    (checkout / "src" / "sase" / "axe" / "__init__.py").write_text("", encoding="utf-8")
    frame.write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "sase.agent.auto_restart.managed_roots.collect_managed_roots",
        lambda: (_root(checkout),),
    )

    modules = probe_modules_for_frames(
        [SimpleNamespace(file=str(frame))],
        target_module="sase.axe.x",
    )
    assert modules == ["sase.axe.x"]
    assert "src.sase.axe.x" not in modules


def test_probe_modules_flat_plugin_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "sase-telegram"
    frame = checkout / "sase_telegram" / "notify.py"
    frame.parent.mkdir(parents=True)
    (checkout / "sase_telegram" / "__init__.py").write_text("", encoding="utf-8")
    frame.write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "sase.agent.auto_restart.managed_roots.collect_managed_roots",
        lambda: (_root(checkout, name="sase-telegram", role="plugin"),),
    )

    modules = probe_modules_for_frames(
        [{"file": str(frame)}],
        target_module="sase_telegram.notify",
    )
    assert modules == ["sase_telegram.notify"]


def test_probe_modules_src_layout_init_and_unmanaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "sase"
    package = checkout / "src" / "sase" / "axe"
    package.mkdir(parents=True)
    (checkout / "src" / "sase" / "__init__.py").write_text("", encoding="utf-8")
    init_file = package / "__init__.py"
    init_file.write_text("", encoding="utf-8")
    outside = tmp_path / "workspace" / "agent.py"
    outside.parent.mkdir()
    outside.write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "sase.agent.auto_restart.managed_roots.collect_managed_roots",
        lambda: (_root(checkout),),
    )

    modules = probe_modules_for_frames(
        [
            SimpleNamespace(file=str(init_file)),
            SimpleNamespace(file=str(outside)),
        ],
        target_module="sase.monitor.continuation_delivery",
    )
    assert modules == ["sase.axe", "sase.monitor.continuation_delivery"]


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required")
def test_pulling_older_commit_counts_as_recent_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "sase"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.name", "Tests")
    _run_git(repo, "config", "user.email", "tests@example.test")
    tracked = repo / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    _run_git(repo, "add", "tracked.txt")
    _run_git(
        repo,
        "commit",
        "-qm",
        "old",
        env={
            "GIT_AUTHOR_DATE": "2020-01-15T12:00:00+00:00",
            "GIT_COMMITTER_DATE": "2020-01-15T12:00:00+00:00",
        },
    )
    old_sha = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    tracked.write_text("two\n", encoding="utf-8")
    _run_git(repo, "add", "tracked.txt")
    _run_git(
        repo,
        "commit",
        "-qm",
        "newer-commit-time",
        env={
            "GIT_AUTHOR_DATE": "2021-01-15T12:00:00+00:00",
            "GIT_COMMITTER_DATE": "2021-01-15T12:00:00+00:00",
        },
    )
    _run_git(repo, "reset", "--hard", "-q", old_sha)

    commit_epoch = float(
        _run_git(repo, "log", "-1", "--format=%ct", "HEAD").stdout.strip()
    )
    assert commit_epoch < time.time() - 86_400 * 30

    monkeypatch.setattr(
        "sase.agent.auto_restart.managed_roots.collect_managed_roots",
        lambda: (_root(repo),),
    )
    monkeypatch.setattr(
        "sase.agent.auto_restart.quiescence._lock_file_mtime",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.agent.auto_restart.quiescence._newest_journal_epoch",
        lambda: None,
    )

    result = check_quiescence(quiescence_seconds=3_600)
    assert result.ok is False
    assert "code changed" in result.reason
    assert result.quiet_seconds is not None
    assert result.quiet_seconds < 60


def _run_git(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=merged,
    )
