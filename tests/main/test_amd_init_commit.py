"""Tests for ``sase amd init`` default git-commit behavior."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

import sase.amd._runner as amd_runner
import sase.amd.init as amd_init
from sase.amd.constants import PROVIDER_SHIM_FILES
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_registry import InitCommandSpec, iter_init_command_specs


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def short_note(body: str) -> str:
    return "---\ntype: short\nparent: AGENTS.md\n---\n" + body


def long_note(body: str, *, description: str = "Long description.") -> str:
    return (
        f"---\ntype: long\nparent: AGENTS.md\ndescription: {description}\n---\n{body}"
    )


def run_amd(*, check: bool = False, no_commit: bool = False) -> int:
    return amd_runner.run_amd_init(argparse.Namespace(check=check, no_commit=no_commit))


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def init_git_repo(root: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "master", str(root)],
        capture_output=True,
        check=True,
    )
    git(root, "config", "user.email", "test@test.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-m", message)


def porcelain(root: Path) -> str:
    return git(root, "status", "--porcelain").stdout


def setup_managed_project(root: Path) -> None:
    """Write a project whose AMD plan generates managed instructions."""
    write(root / "sase.yml", 'amd_h1_title: "Managed Instructions"\n')
    write(root / "memory" / "sase.md", short_note("# SASE\n"))


def test_amd_init_default_commits_managed_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    setup_managed_project(repo)
    commit_all(repo, "initial")

    precommit_calls: list[str] = []

    def fake_precommit(cwd: str) -> bool:
        precommit_calls.append(cwd)
        return True

    monkeypatch.setattr(amd_runner, "run_precommit", fake_precommit)

    assert run_amd(no_commit=False) == 0

    assert [Path(call).resolve() for call in precommit_calls] == [repo.resolve()]
    # AMD committed all of its managed changes; the worktree is clean.
    assert porcelain(repo) == ""
    message = git(repo, "log", "-1", "--format=%B").stdout
    assert "chore: run sase init amd" in message
    assert "TYPE=amd" in message
    tracked = git(repo, "ls-files").stdout.split()
    assert "AGENTS.md" in tracked
    for filename in PROVIDER_SHIM_FILES:
        assert filename in tracked


def test_amd_init_runs_precommit_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    setup_managed_project(repo)
    commit_all(repo, "initial")

    def fake_precommit(cwd: str) -> bool:
        agents = Path(cwd) / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8") + "\n<!-- precommit ran -->\n",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(amd_runner, "run_precommit", fake_precommit)

    assert run_amd(no_commit=False) == 0

    # The precommit mutation is in the committed blob, proving precommit ran
    # before ``git add`` staged the managed paths.
    committed = git(repo, "show", "HEAD:AGENTS.md").stdout
    assert "<!-- precommit ran -->" in committed
    assert porcelain(repo) == ""


def test_amd_init_stages_only_amd_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    setup_managed_project(repo)
    write(repo / "notes.txt", "tracked\n")
    commit_all(repo, "initial")
    # An unrelated, uncommitted user change must not be swept into the AMD commit.
    (repo / "notes.txt").write_text("dirty user edit\n", encoding="utf-8")

    monkeypatch.setattr(amd_runner, "run_precommit", lambda cwd: True)

    assert run_amd(no_commit=False) == 0

    committed_files = git(
        repo, "show", "--name-only", "--format=", "HEAD"
    ).stdout.split()
    assert "AGENTS.md" in committed_files
    assert "notes.txt" not in committed_files
    # The unrelated edit is still present and uncommitted in the worktree.
    assert " M notes.txt" in porcelain(repo)


def test_amd_init_no_commit_preserves_write_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    setup_managed_project(tmp_path)

    precommit = MagicMock(return_value=True)
    git_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(amd_runner, "run_precommit", precommit)
    monkeypatch.setattr(amd_runner.subprocess, "run", git_run)

    assert run_amd(no_commit=True) == 0

    assert (
        (tmp_path / "AGENTS.md")
        .read_text(encoding="utf-8")
        .startswith("# Managed Instructions\n")
    )
    precommit.assert_not_called()
    git_run.assert_not_called()


def test_amd_init_check_does_not_run_git_or_precommit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    setup_managed_project(tmp_path)

    precommit = MagicMock(return_value=True)
    git_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(amd_runner, "run_precommit", precommit)
    monkeypatch.setattr(amd_runner.subprocess, "run", git_run)

    # Drift is present, so check mode reports it with exit 1, but stays read-only
    # even though commits are enabled.
    assert run_amd(check=True, no_commit=False) == 1

    assert not (tmp_path / "AGENTS.md").exists()
    precommit.assert_not_called()
    git_run.assert_not_called()


def test_amd_init_fails_when_changed_path_not_in_git_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if (
        subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    ):
        pytest.skip("temporary directory is unexpectedly inside a git repo")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    setup_managed_project(tmp_path)

    monkeypatch.setattr(amd_runner, "run_precommit", lambda cwd: True)

    assert run_amd(no_commit=False) == 1

    # Files were still written before the repo check failed.
    assert (tmp_path / "AGENTS.md").exists()
    err = capsys.readouterr().err
    assert "is not inside a git repo" in err


def test_amd_init_multi_root_commits_each_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_home = tmp_path / "home"
    project = tmp_path / "project"
    live_config_dir = live_home / ".config" / "sase"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    live_home.mkdir()
    project.mkdir()
    chezmoi_home.mkdir(parents=True)
    init_git_repo(project)
    init_git_repo(chezmoi_home)
    monkeypatch.setenv("HOME", str(live_home))
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", live_config_dir)
    monkeypatch.setattr(amd_init.config_core, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: True)
    write(project / "sase.yml", 'amd_h1_title: "Project Instructions"\n')
    write(project / "memory" / "sase.md", short_note("# Project SASE\n"))
    write(
        chezmoi_home / "dot_config" / "sase" / "sase_athena.yml",
        'amd_h1_title: "Source Home"\n',
    )
    write(chezmoi_home / "memory" / "sase.md", short_note("# Home SASE\n"))
    commit_all(project, "initial project")
    commit_all(chezmoi_home, "initial source")
    monkeypatch.chdir(project)

    precommit_roots: list[Path] = []

    def fake_precommit(cwd: str) -> bool:
        precommit_roots.append(Path(cwd).resolve())
        return True

    monkeypatch.setattr(amd_runner, "run_precommit", fake_precommit)

    assert run_amd(no_commit=False) == 0

    assert set(precommit_roots) == {project.resolve(), chezmoi_home.resolve()}
    for root in (project, chezmoi_home):
        assert porcelain(root) == ""
        message = git(root, "log", "-1", "--format=%B").stdout
        assert "chore: run sase init amd" in message
        assert "TYPE=amd" in message


def test_amd_init_subprocess_commit_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    setup_managed_project(tmp_path)

    git_calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        git_calls.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=f"{tmp_path}\n", stderr="")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        if "commit" in cmd:
            return MagicMock(
                returncode=0,
                stdout="[master abc1234] chore: run sase init amd\n",
                stderr="",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    precommit_calls: list[str] = []
    monkeypatch.setattr(
        amd_runner, "run_precommit", lambda cwd: precommit_calls.append(cwd) or True
    )
    monkeypatch.setattr(amd_runner.subprocess, "run", fake_run)

    assert run_amd(no_commit=False) == 0

    assert len(precommit_calls) == 1
    verbs = [cmd[cmd.index("git") + 3] for cmd in git_calls if cmd[0] == "git"]
    # One rev-parse per changed path (AGENTS.md + four provider shims), then a
    # single staged-diff check and one commit.
    assert verbs == [
        "rev-parse",
        "rev-parse",
        "rev-parse",
        "rev-parse",
        "rev-parse",
        "add",
        "add",
        "add",
        "add",
        "add",
        "diff",
        "commit",
    ]
    commit_cmd = next(cmd for cmd in git_calls if "commit" in cmd and "-m" in cmd)
    assert commit_cmd[commit_cmd.index("-m") + 1] == (
        "chore: run sase init amd\n\nTYPE=amd"
    )


def test_bare_init_amd_commits_before_memory_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare ``sase init`` must hand memory a worktree free of AMD dirt.

    This is the original regression: AMD overwrote ``AGENTS.md`` without
    committing, so the next initializer (memory) inherited an unstaged change
    and its ``git pull --rebase`` failed. With AMD committing its own changes,
    memory starts against a clean worktree.
    """
    repo = tmp_path / "project"
    repo.mkdir()
    init_git_repo(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(amd_init.config_core, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(amd_init.config_core, "CONFIG_DIR", tmp_path / "config")
    # bob-cli shape: a long memory note unreferenced by the minimal AGENTS.md
    # and no configured ``amd_h1_title``.
    write(repo / "sase.yml", "sdd:\n  version_controlled: true\n")
    write(repo / "AGENTS.md", "# Agent Instructions\n\n@memory/sase.md\n")
    write(
        repo / "memory" / "cli_rules.md",
        long_note("# CLI Rules\n", description="CLI rules reference."),
    )
    commit_all(repo, "initial")

    amd_spec = next(spec for spec in iter_init_command_specs() if spec.name == "amd")

    observed: dict[str, object] = {}

    def memory_run(args: argparse.Namespace) -> int:
        observed["status"] = porcelain(repo)
        observed["agents_tracked"] = "AGENTS.md" in git(repo, "ls-files").stdout.split()
        observed["log"] = git(repo, "log", "--format=%s").stdout
        return 0

    memory_spec = InitCommandSpec(
        name="memory",
        label="Memory",
        plan=lambda args: InitPlan(
            command="memory",
            label="Memory",
            summary="update memory",
            actions=(InitAction(Path("memory/sase.md"), "update", "project memory"),),
        ),
        run=memory_run,
    )

    args = argparse.Namespace(
        command="init",
        init_subcommand=None,
        yes=True,
        check=False,
    )

    exit_code = run_init_onboarding(
        args,
        specs=(amd_spec, memory_spec),
        stdin=StringIO(),
        input_func=lambda prompt: "n",
    )

    assert exit_code == 0
    # AMD committed its AGENTS.md overwrite before memory started: no unstaged
    # AMD change remained in the worktree.
    assert observed["status"] == ""
    assert observed["agents_tracked"] is True
    assert "chore: run sase init amd" in str(observed["log"])
