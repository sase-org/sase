"""Shared helpers for ``sase init-skills`` handler tests."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.main import init_skills_handler


def make_args(**overrides: Any) -> argparse.Namespace:
    """Build an argparse.Namespace with init-skills defaults."""
    defaults: dict[str, Any] = {
        "force": True,
        "dry_run": False,
        "provider": None,
        "no_commit": False,
        "no_push": False,
        "no_apply": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def git_cmd_handler(
    *,
    nothing_staged: bool = False,
    commit_rc: int = 0,
    pull_rc: int = 0,
    push_rc: int = 0,
    apply_rc: int = 0,
    repo_check_rc: int = 0,
    repo_check_raises: type[Exception] | None = None,
    apply_raises: type[Exception] | None = None,
):
    """Build a subprocess.run side-effect that routes by command."""

    def handler(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        if not isinstance(cmd, list) or not cmd:
            return MagicMock(returncode=0, stdout="", stderr="")

        if cmd[0] == "git":
            if "rev-parse" in cmd:
                if repo_check_raises is not None:
                    raise repo_check_raises("boom")
                return MagicMock(
                    returncode=repo_check_rc,
                    stdout="/home/x/chezmoi\n" if repo_check_rc == 0 else "",
                    stderr="" if repo_check_rc == 0 else "not a git repo",
                )
            if "add" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "diff" in cmd and "--cached" in cmd:
                return MagicMock(
                    returncode=0 if nothing_staged else 1, stdout="", stderr=""
                )
            if "commit" in cmd:
                return MagicMock(
                    returncode=commit_rc,
                    stdout="[master abc1234] chore: regenerate skills\n"
                    if commit_rc == 0
                    else "",
                    stderr="commit failed" if commit_rc else "",
                )
            if "pull" in cmd:
                return MagicMock(
                    returncode=pull_rc,
                    stdout="Already up to date.\n" if pull_rc == 0 else "",
                    stderr="pull failed" if pull_rc else "",
                )
            if "push" in cmd:
                return MagicMock(
                    returncode=push_rc,
                    stdout="",
                    stderr="To github.com:u/chezmoi.git"
                    if push_rc == 0
                    else "push failed",
                )
        if cmd[0] == "chezmoi":
            if apply_raises is not None:
                raise apply_raises("no chezmoi")
            return MagicMock(
                returncode=apply_rc,
                stdout="",
                stderr="apply failed" if apply_rc else "",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    return handler


def stub_skill_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write one skill template so the handler has something to render."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "foo.md").write_text(
        "---\nname: foo\ndescription: a test skill\nskill: [claude]\n---\n\nbody\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        init_skills_handler,
        "get_sase_package_xprompts_dir",
        lambda: tmp_path,
    )
    return skills_dir


def stub_under_wrapped_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a skill template whose body is hard-wrapped tighter than 120 cols."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "foo.md").write_text(
        "---\n"
        "name: foo\n"
        "description: a test skill\n"
        "skill: [claude]\n"
        "---\n"
        "\n"
        "Use this skill when you need to do many things. This is a long sentence that\n"
        "would normally fit on one line just fine in 120 columns.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        init_skills_handler,
        "get_sase_package_xprompts_dir",
        lambda: tmp_path,
    )
    return skills_dir
