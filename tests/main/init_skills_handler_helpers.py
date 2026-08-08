"""Shared helpers for ``sase init skills`` handler tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.main import _init_skills_manifest as manifest_module, init_skills_handler
from sase.main.init_skills_handler import _get_target_path
from sase.xprompt.models import XPrompt

_OLD_SHA = "1" * 40
_NEW_SHA = "2" * 40
_OTHER_SHA = "3" * 40


def make_args(**overrides: Any) -> argparse.Namespace:
    """Build an argparse.Namespace with init skills defaults."""
    defaults: dict[str, Any] = {
        "allow_dirty": False,
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
    add_rc: int = 0,
    diff_rc: int | None = None,
    commit_rc: int = 0,
    upstream_rc: int = 0,
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
            if "@{u}" in cmd:
                return MagicMock(
                    returncode=upstream_rc,
                    stdout="origin/main\n" if upstream_rc == 0 else "",
                    stderr="" if upstream_rc == 0 else "no upstream",
                )
            if "rev-parse" in cmd:
                if repo_check_raises is not None:
                    raise repo_check_raises("boom")
                return MagicMock(
                    returncode=repo_check_rc,
                    stdout="/home/x/chezmoi\n" if repo_check_rc == 0 else "",
                    stderr="" if repo_check_rc == 0 else "not a git repo",
                )
            if "add" in cmd:
                return MagicMock(
                    returncode=add_rc,
                    stdout="",
                    stderr="add failed" if add_rc else "",
                )
            if "diff" in cmd and "--cached" in cmd:
                rc = diff_rc if diff_rc is not None else 0 if nothing_staged else 1
                return MagicMock(
                    returncode=rc,
                    stdout="",
                    stderr="diff failed" if rc not in (0, 1) else "",
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


def stub_manifest_git(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    incoming: str,
    ancestors: set[tuple[str, str]],
) -> None:
    """Stub git provenance checks used by the skill deploy manifest."""
    source_root = tmp_path / "source"
    skills_dir = source_root / "src" / "sase" / "xprompts" / "skills"
    skills_dir.mkdir(parents=True)

    def fake_run_git(root: Path, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(source_root)
        if args == ("rev-parse", "HEAD"):
            return incoming
        if args[:2] == ("merge-base", "--is-ancestor"):
            if (args[2], args[3]) in ancestors:
                return ""
            raise subprocess.CalledProcessError(1, ["git", *args])
        if args[:3] == ("show", "-s", "--format=%s"):
            return {
                _OLD_SHA: "old source",
                _NEW_SHA: "new source",
                _OTHER_SHA: "other source",
            }[args[3]]
        raise AssertionError(args)

    monkeypatch.setattr(
        manifest_module, "get_sase_package_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(manifest_module, "run_git", fake_run_git)
    monkeypatch.setattr(manifest_module, "_utc_now", lambda: "2026-07-28T13:00:00Z")


def stub_skill_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write one skill template so the handler has something to render."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    src = skills_dir / "foo.md"
    src.write_text(
        "---\nname: foo\ndescription: a test skill\nskill: [claude]\n---\n\nbody\n",
        encoding="utf-8",
    )
    xprompt = XPrompt(
        name="skills/foo",
        skill_name="foo",
        content="body\n",
        source_path=str(src),
        description="a test skill",
        skill=["claude"],
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler, "skill_source_integrity_error", lambda: None
    )
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"skills/foo": xprompt},
    )
    return skills_dir


def stub_claude_skill_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stub one Claude skill source and return its (unwritten) target path."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)
    return _get_target_path("claude", "foo", use_chezmoi=False)


def stub_under_wrapped_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a skill template whose body is hard-wrapped tighter than prettier's."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    body = (
        "Use this skill when you need to do many things. This is a long sentence that\n"
        "would normally be joined and re-wrapped at the repo prose width.\n"
    )
    src = skills_dir / "foo.md"
    src.write_text(
        f"---\nname: foo\ndescription: a test skill\nskill: [claude]\n---\n\n{body}",
        encoding="utf-8",
    )
    xprompt = XPrompt(
        name="skills/foo",
        skill_name="foo",
        content=body,
        source_path=str(src),
        description="a test skill",
        skill=["claude"],
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler,
        "get_all_xprompts",
        lambda project="": {"skills/foo": xprompt},
    )
    return skills_dir
