"""Tests for SDD initialization and generated-file commits."""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.directory_map_assets import DIRECTORY_MAP_ASSET_OVERRIDE_ENV
from sase.logs import tui_git_ops_jsonl_path
from sase.sdd._commit import commit_bare_git_sdd_init_paths
from sase.sdd.files import (
    ensure_bare_git_sdd_initialized,
    ensure_sdd_initialized,
    expected_sdd_generated_paths,
    expected_sdd_readme,
    write_sdd_readme,
)

_GIT_AVAILABLE = shutil.which("git") is not None


def _git(repo: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_ensure_sdd_initialized_writes_generated_files(
    tmp_path: Path,
    real_directory_map_assets: None,
) -> None:
    refreshed = ensure_sdd_initialized(tmp_path)

    expected = set(expected_sdd_generated_paths(str(tmp_path)))
    assert set(refreshed) == expected
    assert all(path.exists() for path in expected)
    directory_map = tmp_path / "sdd" / "assets" / "sdd-directory-map.png"
    assert directory_map.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_ensure_sdd_initialized_uses_directory_map_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override = tmp_path / "placeholder.bin"
    override.write_bytes(b"small directory map")
    monkeypatch.setenv(DIRECTORY_MAP_ASSET_OVERRIDE_ENV, str(override))
    root = tmp_path / "repo"

    ensure_sdd_initialized(root)

    directory_map = root / "sdd" / "assets" / "sdd-directory-map.png"
    assert directory_map.read_bytes() == b"small directory map"


def test_ensure_sdd_initialized_skips_current_tree(tmp_path: Path) -> None:
    write_sdd_readme(str(tmp_path))

    with patch("sase.sdd.files.write_sdd_readme") as write_readme:
        refreshed = ensure_sdd_initialized(tmp_path)

    assert refreshed == ()
    write_readme.assert_not_called()


def test_ensure_sdd_initialized_refreshes_only_stale_paths(tmp_path: Path) -> None:
    write_sdd_readme(str(tmp_path))
    readme = expected_sdd_readme(str(tmp_path)).path
    readme.write_text("stale\n", encoding="utf-8")

    refreshed = ensure_sdd_initialized(tmp_path)

    assert refreshed == (readme,)
    assert readme.read_text(encoding="utf-8").startswith(
        "# Structured Development Docs"
    )


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_ensure_bare_git_sdd_initialized_commits_only_generated_paths(
    tmp_path: Path,
) -> None:
    bare = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    _git(None, "init", "--bare", str(bare))
    _git(None, "clone", str(bare), str(repo))
    (repo / "notes.txt").write_text("dirty\n", encoding="utf-8")

    refreshed = ensure_bare_git_sdd_initialized(repo, commit=True, push=True)

    assert repo / "sdd" / "README.md" in refreshed
    status = _git(
        repo, "-c", "color.status=false", "status", "--short"
    ).stdout.splitlines()
    assert status == ["?? notes.txt"]
    commit_message = _git(repo, "log", "-1", "--format=%B").stdout.strip()
    assert commit_message == "Initialize SDD\n\nSASE_TYPE=init"
    committed_paths = _git(
        repo,
        "show",
        "--name-only",
        "--format=",
        "HEAD",
    ).stdout.splitlines()
    assert committed_paths
    assert all(path.startswith("sdd/") for path in committed_paths)
    remote_tree = _git(
        None,
        "--git-dir",
        str(bare),
        "ls-tree",
        "-r",
        "--name-only",
        "HEAD",
    ).stdout.splitlines()
    assert "sdd/README.md" in remote_tree
    assert "notes.txt" not in remote_tree


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_bare_git_sdd_init_recovers_planted_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    generated = tmp_path / "sdd" / "README.md"
    generated.parent.mkdir()
    generated.write_text("guide\n", encoding="utf-8")
    lock_path = tmp_path / ".git" / "index.lock"
    lock_path.touch()
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001")
    monkeypatch.delenv("SASE_SDD_GIT_LOCK_RETRY_DELAYS", raising=False)

    commit_bare_git_sdd_init_paths(tmp_path, [generated], push=False)

    assert not lock_path.exists()
    assert _git(tmp_path, "show", "--format=", "--name-only", "HEAD").stdout == (
        "sdd/README.md\n"
    )
    assert _git(tmp_path, "status", "--porcelain").stdout == ""


def test_commit_bare_git_sdd_init_paths_push_timeout_is_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_SDD_GIT_LOCAL_TIMEOUT", "3")
    monkeypatch.setenv("SASE_SDD_GIT_NETWORK_TIMEOUT", "7")
    generated = tmp_path / "sdd" / "README.md"
    generated.parent.mkdir()
    generated.write_text("guide\n", encoding="utf-8")
    calls: list[tuple[list[str], float | None]] = []

    def git_subcommand(cmd: list[str]) -> str:
        index = 1
        while index + 1 < len(cmd) and cmd[index] == "-c":
            index += 2
        return cmd[index] if index < len(cmd) else ""

    def fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, kwargs.get("timeout")))  # type: ignore[arg-type]
        if git_subcommand(cmd) == "diff":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if git_subcommand(cmd) == "push":
            raise subprocess.TimeoutExpired(
                cmd=cmd,
                timeout=kwargs.get("timeout"),
                output="",
                stderr="still running",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    # A push timeout is best-effort: the local commit is preserved and the
    # timeout must not propagate to the caller (which would abort an agent
    # launch via ws_get_workspace_directory).
    with (
        patch("sase.sdd._commit.subprocess.run", side_effect=fake_run),
        patch("sase.sdd._repository_transaction.require_sdd_repository_health"),
    ):
        commit_bare_git_sdd_init_paths(tmp_path, [generated], push=True)

    assert calls[0][1] == 3.0
    assert git_subcommand(calls[-1][0]) == "push"
    assert calls[-1][1] == 7.0
    records = [
        json.loads(line)
        for line in tui_git_ops_jsonl_path().read_text(encoding="utf-8").splitlines()
    ]
    push_timeout = [
        record for record in records if record["operation"] == "bare_git_sdd_init.push"
    ]
    assert push_timeout[-1]["status"] == "timeout"
    assert push_timeout[-1]["timeout_seconds"] == 7.0


def test_commit_bare_git_sdd_init_paths_push_rejection_is_best_effort(
    tmp_path: Path,
) -> None:
    """A non-fast-forward push rejection must not abort the caller.

    Regression: bare-git agent launches call this with push=True and
    raise_on_error=True; a remote-ahead rejection previously propagated and
    failed the launch.
    """
    generated = tmp_path / "sdd" / "README.md"
    generated.parent.mkdir()
    generated.write_text("guide\n", encoding="utf-8")

    def fake_run(
        cmd: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if cmd[:2] == ["git", "push"]:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=cmd,
                output="",
                stderr="! [rejected] HEAD -> master (fetch first)",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    # Must return normally (no exception) despite the rejected push.
    with (
        patch("sase.sdd._commit.subprocess.run", side_effect=fake_run),
        patch("sase.sdd._repository_transaction.require_sdd_repository_health"),
    ):
        commit_bare_git_sdd_init_paths(tmp_path, [generated], push=True)
