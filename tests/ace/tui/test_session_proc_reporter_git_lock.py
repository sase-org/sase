"""Reporter-backed Git index-lock recovery regressions."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.dev_update.command import run_dev_update_command
from tests.ace.tui._session_reporter import session_reporter
from tests.git_lock_test_helpers import age_git_index_lock


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


def _commit(repo: Path, message: str, content: str) -> str:
    (repo / "file.txt").write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def _behind_ff_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    first = _commit(repo, "one", "one\n")
    target = _commit(repo, "two", "two\n")
    subprocess.run(["git", "reset", "--hard", "-q", first], cwd=repo, check=True)
    return repo, target


def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def test_reporter_dev_command_runner_recovers_abandoned_ff_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, target = _behind_ff_repo(tmp_path)
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    age_git_index_lock(lock)
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")
    reporter = session_reporter(proc_type="sase-update")

    result = reporter.dev_command_runner()(
        ["git", "-C", str(repo), "merge", "--ff-only", target]
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert _head(repo) == target
    assert (repo / "file.txt").read_text(encoding="utf-8") == "two\n"
    assert not lock.exists()
    output = reporter.proc.get_live_output()
    assert "Removed stale git index lock" in output
    assert "retrying" in output.lower()


def test_run_dev_update_command_capture_recovers_abandoned_ff_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, target = _behind_ff_repo(tmp_path)
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    age_git_index_lock(lock)
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")

    result = run_dev_update_command(
        ("git", "-C", str(repo), "merge", "--ff-only", target)
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert _head(repo) == target
    assert not lock.exists()


def test_run_dev_update_command_streaming_recovers_abandoned_ff_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, target = _behind_ff_repo(tmp_path)
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    age_git_index_lock(lock)
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")
    lines: list[str] = []

    def on_output(stream: str, line: str) -> None:
        lines.append(f"{stream}:{line}")

    result = run_dev_update_command(
        ("git", "-C", str(repo), "merge", "--ff-only", target),
        on_output=on_output,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert _head(repo) == target
    assert not lock.exists()
    assert any("Fast-forward" in line or "Updating" in line for line in lines)
