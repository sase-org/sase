"""Agent-context home-memory deferral for ``sase memory init``."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.main import _init_memory_apply, _init_memory_support
from sase.main._init_chezmoi_deploy import defer_chezmoi_deploy
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    run_memory,
)


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _run_git(path, "init", "-q", "-b", "main")
    _run_git(path, "config", "user.name", "SASE Test")
    _run_git(path, "config", "user.email", "sase-test@example.invalid")
    (path / "README").write_text("chezmoi source\n", encoding="utf-8")
    home = path / "home"
    home.mkdir()
    (home / ".keep").write_text("", encoding="utf-8")
    config = home / "dot_config" / "sase" / "sase.yml"
    config.parent.mkdir(parents=True)
    config.write_text("linked_repos: []\n", encoding="utf-8")
    _run_git(path, "add", "-A")
    _run_git(path, "commit", "-q", "-m", "initial")
    return path


def _install_dummy_chezmoi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    chezmoi = bin_dir / "chezmoi"
    chezmoi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    chezmoi.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return chezmoi


def _prepare_chezmoi_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_root = _init_git_repo(tmp_path / "chezmoi")
    chezmoi_home = chezmoi_root / "home"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(_init_memory_support, "CHEZMOI_HOME", chezmoi_home)
    _install_dummy_chezmoi(tmp_path, monkeypatch)
    return project_root, chezmoi_root, chezmoi_home


def _pin_owner_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )


def test_agent_memory_init_skips_home_write_commit_and_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root, chezmoi_root, chezmoi_home = _prepare_chezmoi_home(
        tmp_path, monkeypatch
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "home-agent")
    head_before = _run_git(chezmoi_root, "rev-parse", "HEAD")

    assert run_memory() == 0

    out = capsys.readouterr().out
    assert "home memory refresh deferred until land (agent run)" in out
    assert "rerun `sase memory init` outside an agent after landing" in out
    assert str(chezmoi_home / "sase" / "memory" / "sase.md") in out
    assert (project_root / "sase" / "memory" / "sase.md").is_file()
    assert not (chezmoi_home / "sase" / "memory" / "sase.md").exists()
    assert not (chezmoi_home / "AGENTS.md").exists()
    assert _run_git(chezmoi_root, "rev-parse", "HEAD") == head_before
    assert _run_git(chezmoi_root, "status", "--porcelain") == ""


def test_agent_memory_init_gate_deploys_home_with_agent_trailer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_root, chezmoi_root, chezmoi_home = _prepare_chezmoi_home(
        tmp_path, monkeypatch
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "home-agent")
    monkeypatch.setenv("SASE_GATE_COMMAND", "1")
    _pin_owner_identity(monkeypatch)
    head_before = _run_git(chezmoi_root, "rev-parse", "HEAD")

    assert run_memory() == 0

    assert (chezmoi_home / "sase" / "memory" / "sase.md").is_file()
    head_after = _run_git(chezmoi_root, "rev-parse", "HEAD")
    assert head_after != head_before
    message = _run_git(chezmoi_root, "log", "-1", "--format=%B")
    assert "SASE_TYPE=memory" in message
    assert "SASE_AGENT=alice.athena.home-agent" in message


def test_agent_memory_init_bypass_deploys_home_and_prints_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _init_memory_apply._emitted_home_bypass_reasons.clear()
    _project_root, chezmoi_root, chezmoi_home = _prepare_chezmoi_home(
        tmp_path, monkeypatch
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "home-agent")
    monkeypatch.setenv("SASE_HOME_MEMORY_DEPLOY_BYPASS", "repair-home")
    _pin_owner_identity(monkeypatch)

    assert run_memory() == 0
    assert run_memory() == 0

    captured = capsys.readouterr()
    assert captured.err.count("repair-home") == 1
    assert "SASE_HOME_MEMORY_DEPLOY_BYPASS: repair-home" in captured.err
    assert (chezmoi_home / "sase" / "memory" / "sase.md").is_file()
    message = _run_git(chezmoi_root, "log", "-1", "--format=%B")
    assert "SASE_AGENT=alice.athena.home-agent" in message


def test_human_memory_init_still_deploys_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_root, chezmoi_root, chezmoi_home = _prepare_chezmoi_home(
        tmp_path, monkeypatch
    )
    head_before = _run_git(chezmoi_root, "rev-parse", "HEAD")

    assert run_memory() == 0

    assert (chezmoi_home / "sase" / "memory" / "sase.md").is_file()
    assert _run_git(chezmoi_root, "rev-parse", "HEAD") != head_before
    message = _run_git(chezmoi_root, "log", "-1", "--format=%B")
    assert "SASE_TYPE=memory" in message
    assert "SASE_AGENT=" not in message


def test_agent_memory_init_deferred_chezmoi_collects_no_home_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_chezmoi_home(tmp_path, monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "home-agent")

    with defer_chezmoi_deploy() as deferred:
        assert run_memory() == 0

    assert deferred.paths == []
