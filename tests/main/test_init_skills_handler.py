"""Tests for the 'sase init-skills' handler, especially the chezmoi auto-deploy."""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import (
    _deploy_to_chezmoi,
    handle_init_skills_command,
)


def _make_args(**overrides: Any) -> argparse.Namespace:
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


def _git_cmd_handler(
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


# === Tests for _deploy_to_chezmoi ===


def test_deploy_happy_path_runs_full_sequence() -> None:
    """add → commit → pull → push → chezmoi apply in order."""
    args = _make_args()
    paths = [Path("/home/x/chezmoi/home/dot_claude/skills/foo/SKILL.md")]

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(),
    ) as mock_run:
        rc = _deploy_to_chezmoi(paths, args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    verbs = [cmd[cmd.index("git") + 3] if cmd[0] == "git" else cmd[0] for cmd in calls]
    assert verbs == ["rev-parse", "add", "diff", "commit", "pull", "push", "chezmoi"]


def test_deploy_no_commit_skips_everything() -> None:
    """--no-commit: handler returns immediately without running anything."""
    args = _make_args(no_commit=True)

    with patch.object(init_skills_handler.subprocess, "run") as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    mock_run.assert_not_called()


def test_deploy_no_push_stops_after_commit() -> None:
    """--no-push: stage + commit, but no pull/push/apply."""
    args = _make_args(no_push=True)

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    commands = [
        cmd[cmd.index("git") + 3] if cmd[0] == "git" else cmd[0] for cmd in calls
    ]
    assert commands == ["rev-parse", "add", "diff", "commit"]


def test_deploy_no_apply_stops_after_push() -> None:
    """--no-apply: run through push but skip chezmoi apply."""
    args = _make_args(no_apply=True)

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert all(cmd[0] != "chezmoi" for cmd in calls)
    assert any("push" in cmd for cmd in calls)


def test_deploy_nothing_staged_skips_commit_and_later_steps() -> None:
    """If git diff --cached --quiet returns 0, no commit/push/apply."""
    args = _make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(nothing_staged=True),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any("commit" in cmd for cmd in calls)
    assert not any("push" in cmd for cmd in calls)
    assert not any(cmd[0] == "chezmoi" for cmd in calls)


def test_deploy_not_a_git_repo_skips_gracefully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git rev-parse --show-toplevel failure → warn and return 0."""
    args = _make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(repo_check_rc=1),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert len(calls) == 1
    assert "rev-parse" in calls[0]
    err = capsys.readouterr().err
    assert "not a git repo" in err


def test_deploy_git_missing_skips_gracefully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If git binary is missing (FileNotFoundError) on repo check, skip with warning."""
    args = _make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(repo_check_raises=FileNotFoundError),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    assert "git not found" in capsys.readouterr().err


def test_deploy_push_failure_returns_nonzero_and_skips_apply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Push failure: no chezmoi apply, non-zero exit, stderr has reason."""
    args = _make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(push_rc=1),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any(cmd[0] == "chezmoi" for cmd in calls)
    assert "push failed" in capsys.readouterr().err


def test_deploy_pull_failure_returns_nonzero_and_skips_push(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pull failure: no push, no apply, non-zero exit."""
    args = _make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(pull_rc=1),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any("push" in cmd for cmd in calls)
    assert not any(cmd[0] == "chezmoi" for cmd in calls)
    assert "pull failed" in capsys.readouterr().err


def test_deploy_chezmoi_missing_warns_but_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """chezmoi binary missing → warning and exit 0 (git side succeeded)."""
    args = _make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(apply_raises=FileNotFoundError),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    assert "chezmoi not found" in capsys.readouterr().err


def test_deploy_chezmoi_apply_failure_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """chezmoi apply failure (non-zero exit) surfaces as non-zero return."""
    args = _make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=_git_cmd_handler(apply_rc=1),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    assert "chezmoi apply failed" in capsys.readouterr().err


def test_deploy_provider_filter_in_commit_message() -> None:
    """--provider=claude → commit message mentions provider."""
    args = _make_args(provider="claude")
    captured: list[list[str]] = []

    def handler(*a: Any, **kw: Any) -> MagicMock:
        cmd = a[0] if a else kw.get("cmd", [])
        captured.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(init_skills_handler.subprocess, "run", side_effect=handler):
        _deploy_to_chezmoi([Path("/x/a")], args)

    commit_calls = [c for c in captured if "commit" in c and "-m" in c]
    assert commit_calls, "No commit call observed"
    msg = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert "claude" in msg


# === Tests for handle_init_skills_command trigger conditions ===


def _stub_skill_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


def test_handler_no_use_chezmoi_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """use_chezmoi=False: _deploy_to_chezmoi is never called."""
    _stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(_make_args())

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_dry_run_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run: no deploy even if use_chezmoi=True."""
    _stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    deploy_mock = MagicMock()
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(_make_args(dry_run=True))

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_zero_written_does_not_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When nothing is written (e.g. no skill field), no deploy."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # No `skill:` field → nothing will be rendered
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
        handle_init_skills_command(_make_args())

    assert exc.value.code == 0
    deploy_mock.assert_not_called()


def test_handler_use_chezmoi_triggers_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: use_chezmoi + wrote at least one file → deploy is called."""
    _stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)

    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(_make_args())

    assert exc.value.code == 0
    deploy_mock.assert_called_once()
    passed_paths = deploy_mock.call_args.args[0]
    assert len(passed_paths) == 1
    assert passed_paths[0].name == "SKILL.md"


def test_handler_propagates_deploy_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-zero return from _deploy_to_chezmoi becomes the process exit code."""
    _stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)

    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(
        init_skills_handler, "_deploy_to_chezmoi", MagicMock(return_value=1)
    )

    with pytest.raises(SystemExit) as exc:
        handle_init_skills_command(_make_args())

    assert exc.value.code == 1
