"""Tests for the dev-update command runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.dev_update.execute import run_dev_update_command


def test_run_dev_update_command_disables_git_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("sase.dev_update.command.subprocess.run", fake_run)

    result = run_dev_update_command(("git", "fetch", "origin"))

    assert result.returncode == 0
    assert captured["stdin"] is subprocess.DEVNULL
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "never"


def test_run_dev_update_command_merges_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr("sase.dev_update.command.subprocess.run", fake_run)

    result = run_dev_update_command(
        ("just", "rust-dev-install-uv-tool"),
        env={"SASE_RUST_DEV_PROFILE": "release"},
    )

    assert result.returncode == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["PATH"] == "/usr/bin"
    assert env["SASE_RUST_DEV_PROFILE"] == "release"


def test_run_dev_update_command_recovers_stale_git_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock = git_dir / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    attempts = 0

    def fake_run(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal attempts
        attempts += 1
        if lock.exists():
            return subprocess.CompletedProcess(
                argv,
                128,
                stdout="",
                stderr=f"fatal: Unable to create '{lock}': File exists.",
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")
    monkeypatch.setattr("sase.dev_update.command.subprocess.run", fake_run)

    result = run_dev_update_command(("git", "-C", str(tmp_path), "add", "-A"))

    assert result.returncode == 0
    assert attempts == 4
    assert not lock.exists()
