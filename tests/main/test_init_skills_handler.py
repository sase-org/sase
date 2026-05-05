"""Tests for ``sase init-skills`` command dispatch and target paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import _get_target_path, handle_init_skills_command
from tests.main.init_skills_handler_helpers import make_args, stub_skill_source


def test_handler_no_use_chezmoi_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """use_chezmoi=False: _deploy_to_chezmoi is never called."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_dry_run_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run: no deploy even if use_chezmoi=True."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args(dry_run=True))

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_zero_written_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When nothing is written (e.g. no skill field), no deploy."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "foo.md").write_text(
        "---\nname: foo\ndescription: x\n---\n\nbody\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        init_skills_handler, "get_sase_package_xprompts_dir", lambda: tmp_path
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_use_chezmoi_triggers_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: use_chezmoi + wrote at least one file -> deploy is called."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)

    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 0
    deploy_mock.assert_called_once()
    passed_paths = deploy_mock.call_args.args[0]
    assert len(passed_paths) == 1
    assert passed_paths[0].name == "SKILL.md"


def test_handler_propagates_deploy_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-zero return from _deploy_to_chezmoi becomes the process exit code."""
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(
        init_skills_handler, "_deploy_to_chezmoi", MagicMock(return_value=1)
    )

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(make_args())

    assert exc.value.code == 1


def test_get_target_path_claude_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude deploys to ~/.claude/skills/<name>/SKILL.md."""
    monkeypatch.setattr(Path, "home", lambda: Path("/home/u"))
    target = _get_target_path("claude", "foo", use_chezmoi=False)
    assert target == Path("/home/u/.claude/skills/foo/SKILL.md")


def test_get_target_path_claude_chezmoi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude under chezmoi deploys to <CHEZMOI_HOME>/dot_claude/skills/..."""
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", Path("/c/home"))
    target = _get_target_path("claude", "foo", use_chezmoi=True)
    assert target == Path("/c/home/dot_claude/skills/foo/SKILL.md")
