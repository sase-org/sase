from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from sase.memory.episodes.auto_build import DEFAULT_AUTO_BUILD_LIMIT
from sase.memory.episodes._auto_build_types import EpisodeAutoBuildReport


def test_memory_episodes_chop_uses_env_target_from_state_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_memory_episodes")
    state_dir = tmp_path / ".sase" / "axe" / "lumberjacks" / "memory"
    repo_root = tmp_path / "repo"
    state_dir.mkdir(parents=True)
    repo_root.mkdir()
    calls: list[dict[str, Any]] = []

    def fake_run_episode_auto_build(
        project: str,
        *,
        repo_root: Path | str | None,
        limit: int | None,
        dry_run: bool,
    ) -> EpisodeAutoBuildReport:
        calls.append(
            {
                "project": project,
                "repo_root": repo_root,
                "limit": limit,
                "dry_run": dry_run,
            }
        )
        return _report(project, tmp_path / "episodes", dry_run=dry_run)

    monkeypatch.chdir(state_dir)
    monkeypatch.setenv(script.PROJECT_ENV, "sase")
    monkeypatch.setenv(script.REPO_ROOT_ENV, str(repo_root))
    monkeypatch.setattr(sys, "argv", ["sase_chop_memory_episodes"])
    monkeypatch.setattr(script, "run_episode_auto_build", fake_run_episode_auto_build)

    script.main()

    assert calls == [
        {
            "project": "sase",
            "repo_root": repo_root,
            "limit": DEFAULT_AUTO_BUILD_LIMIT,
            "dry_run": False,
        }
    ]
    out = capsys.readouterr().out
    assert "memory_episodes:" in out
    assert "project=sase" in out
    assert f"repo_root={repo_root}" in out


def test_memory_episodes_chop_cli_target_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_memory_episodes")
    env_root = tmp_path / "env-repo"
    cli_root = tmp_path / "cli-repo"
    env_root.mkdir()
    cli_root.mkdir()
    calls: list[dict[str, Any]] = []

    def fake_run_episode_auto_build(
        project: str,
        *,
        repo_root: Path | str | None,
        limit: int | None,
        dry_run: bool,
    ) -> EpisodeAutoBuildReport:
        calls.append(
            {
                "project": project,
                "repo_root": repo_root,
                "limit": limit,
                "dry_run": dry_run,
            }
        )
        return _report(project, tmp_path / "episodes", dry_run=dry_run)

    monkeypatch.setenv(script.PROJECT_ENV, "env-project")
    monkeypatch.setenv(script.REPO_ROOT_ENV, str(env_root))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sase_chop_memory_episodes",
            "-p",
            "cli-project",
            "-r",
            str(cli_root),
            "-l",
            "7",
            "-D",
            "-j",
        ],
    )
    monkeypatch.setattr(script, "run_episode_auto_build", fake_run_episode_auto_build)

    script.main()

    assert calls == [
        {
            "project": "cli-project",
            "repo_root": cli_root,
            "limit": 7,
            "dry_run": True,
        }
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["project"] == "cli-project"
    assert payload["dry_run"] is True
    assert payload["target_repo_root"] == str(cli_root)


def test_memory_episodes_chop_falls_back_to_cwd_for_manual_invocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    script = importlib.import_module("sase.scripts.sase_chop_memory_episodes")
    repo_root = tmp_path / "repo-cwd"
    repo_root.mkdir()
    calls: list[dict[str, Any]] = []
    inferred_from: list[Path] = []

    def fake_project_memory_name(root: Path) -> str:
        inferred_from.append(root)
        return "cwd-project"

    def fake_run_episode_auto_build(
        project: str,
        *,
        repo_root: Path | str | None,
        limit: int | None,
        dry_run: bool,
    ) -> EpisodeAutoBuildReport:
        calls.append(
            {
                "project": project,
                "repo_root": repo_root,
                "limit": limit,
                "dry_run": dry_run,
            }
        )
        return _report(project, tmp_path / "episodes", dry_run=dry_run)

    monkeypatch.chdir(repo_root)
    monkeypatch.delenv(script.PROJECT_ENV, raising=False)
    monkeypatch.delenv(script.REPO_ROOT_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["sase_chop_memory_episodes"])
    monkeypatch.setattr(script, "project_memory_name", fake_project_memory_name)
    monkeypatch.setattr(script, "run_episode_auto_build", fake_run_episode_auto_build)

    script.main()

    assert inferred_from == [repo_root]
    assert calls == [
        {
            "project": "cwd-project",
            "repo_root": repo_root,
            "limit": DEFAULT_AUTO_BUILD_LIMIT,
            "dry_run": False,
        }
    ]


def _report(
    project: str,
    episodes_dir: Path,
    *,
    dry_run: bool,
) -> EpisodeAutoBuildReport:
    return EpisodeAutoBuildReport(
        project=project,
        episodes_dir=str(episodes_dir),
        status="dry_run" if dry_run else "idle",
        message="test report",
        dry_run=dry_run,
        lock_acquired=True,
        lock_wait_seconds=0.0,
        checkpoint_before=None,
        checkpoint_after=None,
    )
