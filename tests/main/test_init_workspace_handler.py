"""Tests for ``sase init workspace``."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_registry import InitCommandSpec
from sase.main.init_workspace_handler import (
    LINKED_REPO_GITIGNORE_PATTERN,
    plan_init_workspace,
    run_init_workspace,
)


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "check": False,
        "diff": False,
        "no_commit": True,
        "yes": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_plan_reports_missing_rule_with_full_content(
    tmp_path: Path, monkeypatch
) -> None:
    _git_init(tmp_path)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("/build", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    plan = plan_init_workspace(_args())

    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.operation == "update"
    assert action.path == gitignore
    assert action.new_content == "/build\n/sase/repos/\n"


def test_plan_is_current_when_rule_exists(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    (tmp_path / ".gitignore").write_text(
        f"{LINKED_REPO_GITIGNORE_PATTERN}\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert plan_init_workspace(_args()).actions == ()


def test_plan_is_empty_outside_git_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert plan_init_workspace(_args()).actions == ()


def test_apply_is_idempotent_and_preserves_content(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("/build", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert run_init_workspace(_args()) == 0
    first = gitignore.read_text(encoding="utf-8")
    assert first == "/build\n/sase/repos/\n"
    assert run_init_workspace(_args()) == 0
    assert gitignore.read_text(encoding="utf-8") == first


def test_apply_commits_only_the_managed_gitignore(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test User"],
        check=True,
    )
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("leave untracked", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert run_init_workspace(_args(no_commit=False)) == 0

    subject = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert subject == "chore: initialize SASE workspace ignores"
    assert unrelated.exists()
    status = subprocess.run(
        ["git", "-C", str(tmp_path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == "?? unrelated.txt\n"


def test_scoped_check_exit_codes(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert run_init_workspace(_args(check=True)) == 1
    (tmp_path / ".gitignore").write_text(
        f"{LINKED_REPO_GITIGNORE_PATTERN}\n", encoding="utf-8"
    )
    assert run_init_workspace(_args(check=True)) == 0


def test_workspace_spec_appears_in_bare_onboarding_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _git_init(tmp_path)
    monkeypatch.chdir(tmp_path)
    spec = InitCommandSpec(
        name="workspace",
        label="Workspace",
        plan=plan_init_workspace,
        run=run_init_workspace,
    )

    exit_code = run_init_onboarding(
        _args(check=True),
        specs=(spec,),
    )

    assert exit_code == 1
    assert "init workspace" in capsys.readouterr().out
