"""Tests for the ``sase init skills`` chezmoi auto-deploy path."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.main import _init_chezmoi_deploy
from sase.memory.locks import LockTimeoutError
from sase.main.init_skills_handler import _deploy_to_chezmoi
from tests.main.init_skills_handler_helpers import git_cmd_handler, make_args


def test_deploy_happy_path_runs_full_sequence() -> None:
    """add -> commit -> pull -> push -> chezmoi apply in order."""
    args = make_args()
    paths = [Path("/home/x/chezmoi/home/dot_claude/skills/foo/SKILL.md")]

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(),
    ) as mock_run:
        rc = _deploy_to_chezmoi(paths, args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    verbs = [cmd[cmd.index("git") + 3] if cmd[0] == "git" else cmd[0] for cmd in calls]
    assert verbs == [
        "rev-parse",
        "add",
        "diff",
        "commit",
        "rev-parse",
        "pull",
        "push",
        "chezmoi",
    ]


def test_deploy_no_commit_skips_everything() -> None:
    """--no-commit: handler returns immediately without running anything."""
    args = make_args(no_commit=True)

    with patch.object(_init_chezmoi_deploy.subprocess, "run") as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    mock_run.assert_not_called()


def test_deploy_no_push_stops_after_commit() -> None:
    """--no-push: stage + commit, but no pull/push/apply."""
    args = make_args(no_push=True)

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(),
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
    args = make_args(no_apply=True)

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert all(cmd[0] != "chezmoi" for cmd in calls)
    assert any("@{u}" in cmd for cmd in calls)
    assert any("push" in cmd for cmd in calls)


def test_deploy_nothing_staged_skips_commit_and_later_steps() -> None:
    """If git diff --cached --quiet returns 0, no commit/push/apply."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(nothing_staged=True),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any("commit" in cmd for cmd in calls)
    assert not any("push" in cmd for cmd in calls)
    assert not any(cmd[0] == "chezmoi" for cmd in calls)


def test_deploy_git_add_failure_returns_nonzero_and_skips_commit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git add failure should stop before commit/push/apply."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(add_rc=128),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any("commit" in cmd for cmd in calls)
    assert not any("push" in cmd for cmd in calls)
    assert not any(cmd[0] == "chezmoi" for cmd in calls)
    err = capsys.readouterr().err
    assert "git add failed" in err
    assert "add failed" in err


def test_deploy_staged_diff_failure_returns_nonzero_and_skips_commit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git diff --cached --quiet errors should not be treated as staged work."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(diff_rc=128),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any("commit" in cmd for cmd in calls)
    assert not any("push" in cmd for cmd in calls)
    assert not any(cmd[0] == "chezmoi" for cmd in calls)
    err = capsys.readouterr().err
    assert "staged diff check failed" in err
    assert "diff failed" in err


def test_deploy_not_a_git_repo_skips_gracefully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git rev-parse --show-toplevel failure -> warn and return 0."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(repo_check_rc=1),
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
    """If git binary is missing on repo check, skip with warning."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(repo_check_raises=FileNotFoundError),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    assert "git not found" in capsys.readouterr().err


def test_deploy_push_failure_returns_nonzero_and_skips_apply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Push failure: no chezmoi apply, non-zero exit, stderr has reason."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(push_rc=1),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any(cmd[0] == "chezmoi" for cmd in calls)
    assert "push failed" in capsys.readouterr().err


def test_deploy_no_upstream_skips_pull_push_apply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A local-only repo commits successfully and skips network deploy steps."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(upstream_rc=128),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert any("@{u}" in cmd for cmd in calls)
    assert not any("pull" in cmd for cmd in calls)
    assert not any("push" in cmd for cmd in calls)
    assert not any(cmd[0] == "chezmoi" for cmd in calls)
    assert "no upstream configured; skipping pull/push" in capsys.readouterr().out


def test_deploy_pull_failure_returns_nonzero_and_skips_push(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pull failure: no push, no apply, non-zero exit."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(pull_rc=1),
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
    """chezmoi binary missing -> warning and exit 0 (git side succeeded)."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(apply_raises=FileNotFoundError),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    assert "chezmoi not found" in capsys.readouterr().err


def test_deploy_chezmoi_apply_failure_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """chezmoi apply failure (non-zero exit) surfaces as non-zero return."""
    args = make_args()

    with patch.object(
        _init_chezmoi_deploy.subprocess,
        "run",
        side_effect=git_cmd_handler(apply_rc=1),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    assert "chezmoi apply --force failed" in capsys.readouterr().err


def test_deploy_provider_filter_in_commit_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--provider=claude -> commit message mentions provider."""
    args = make_args(provider="claude")
    captured: list[list[str]] = []
    for name in (
        "SASE_AGENT_WORKSPACE_NUM",
        "SASE_GIT_WORKSPACE_NUM",
        "SASE_GH_WORKSPACE_NUM",
        "SASE_GIT_WORKSPACE_DIR",
        "SASE_GH_WORKSPACE_DIR",
        "SASE_ACTIVE_PROJECT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    def handler(*a: Any, **kw: Any) -> MagicMock:
        cmd = a[0] if a else kw.get("cmd", [])
        captured.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(_init_chezmoi_deploy.subprocess, "run", side_effect=handler):
        _deploy_to_chezmoi([Path("/x/a")], args)

    commit_calls = [c for c in captured if "commit" in c and "-m" in c]
    assert commit_calls, "No commit call observed"
    msg = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert msg == (
        "chore: regenerate claude skills via sase skill init\n\nSASE_TYPE=skills"
    )


def test_deploy_skill_commit_message_records_source_workspace_and_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skill deploy commits carry enough trailers to attribute the source."""
    args = make_args(no_push=True)
    captured: list[list[str]] = []
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-agent")
    monkeypatch.setenv("SASE_GIT_WORKSPACE_NUM", "7")
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", "/workspace/sase_7")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )

    def handler(*a: Any, **kw: Any) -> MagicMock:
        cmd = a[0] if a else kw.get("cmd", [])
        captured.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(_init_chezmoi_deploy.subprocess, "run", side_effect=handler):
        _deploy_to_chezmoi(
            [Path("/x/a")],
            args,
            source_commit="abcdef1234567890",
        )

    commit_calls = [c for c in captured if "commit" in c and "-m" in c]
    assert commit_calls, "No commit call observed"
    msg = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert msg == (
        "chore: regenerate skills via sase skill init\n\n"
        "SASE_TYPE=skills\n"
        "SASE_SOURCE_REVISION=abcdef1234567890\n"
        "SASE_WORKSPACE=7:/workspace/sase_7\n"
        "SASE_AGENT=alice.athena.phase-agent"
    )


def test_deploy_behavior_auto_commit_type_tags_message() -> None:
    """Shared deploy helper applies the caller-provided auto-commit type."""
    captured: list[list[str]] = []

    def handler(*a: Any, **kw: Any) -> MagicMock:
        cmd = a[0] if a else kw.get("cmd", [])
        captured.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(_init_chezmoi_deploy.subprocess, "run", side_effect=handler):
        _init_chezmoi_deploy.deploy_to_chezmoi(
            [Path("/x/a")],
            _init_chezmoi_deploy.ChezmoiDeployBehavior(
                command_label="init",
                commit_message="chore: run sase init",
                auto_commit_type="init",
                no_push=True,
            ),
        )

    commit_calls = [c for c in captured if "commit" in c and "-m" in c]
    assert commit_calls, "No commit call observed"
    msg = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert msg == "chore: run sase init\n\nSASE_TYPE=init"


def test_deferred_deploy_keeps_skill_provenance_trailers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare ``sase init`` deferral gets the same skill attribution trailers."""
    captured: list[list[str]] = []
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-agent")
    monkeypatch.setenv("SASE_GIT_WORKSPACE_NUM", "9")
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", "/workspace/sase_9")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )

    def handler(*a: Any, **kw: Any) -> MagicMock:
        cmd = a[0] if a else kw.get("cmd", [])
        captured.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        _init_chezmoi_deploy.defer_chezmoi_deploy() as deferred,
        patch.object(_init_chezmoi_deploy.subprocess, "run", side_effect=handler),
    ):
        assert _init_chezmoi_deploy.defer_chezmoi_paths(
            [Path("/x/a")],
            commit_tags={
                "SOURCE_REVISION": "fedcba9876543210",
                "WORKSPACE": "9:/workspace/sase_9",
            },
            include_runtime_commit_tags=True,
        )
        assert _init_chezmoi_deploy.deploy_deferred_chezmoi(deferred) == 0

    commit_calls = [c for c in captured if "commit" in c and "-m" in c]
    assert commit_calls, "No commit call observed"
    msg = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert msg == (
        "chore: run sase init\n\n"
        "SASE_TYPE=init\n"
        "SASE_SOURCE_REVISION=fedcba9876543210\n"
        "SASE_WORKSPACE=9:/workspace/sase_9\n"
        "SASE_AGENT=alice.athena.phase-agent"
    )


def test_deploy_holds_chezmoi_lock_during_mutating_sequence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The shared deploy lock covers add/diff/commit/pull/push/apply."""
    locked = False
    seen_inside_lock: list[str] = []

    @contextmanager
    def fake_locked_file(path: Path, _flags: int, **kwargs: Any):
        nonlocal locked
        kwargs["on_wait"](path)
        locked = True
        try:
            yield
        finally:
            locked = False

    base_handler = git_cmd_handler()

    def handler(*a: Any, **kw: Any) -> MagicMock:
        cmd = a[0] if a else kw.get("cmd", [])
        if cmd[0] == "git" and "--show-toplevel" in cmd:
            assert not locked
        else:
            assert locked
            seen_inside_lock.append(cmd[0] if cmd[0] != "git" else cmd[3])
        return base_handler(*a, **kw)

    with (
        patch.object(_init_chezmoi_deploy, "locked_file", fake_locked_file),
        patch.object(_init_chezmoi_deploy.subprocess, "run", side_effect=handler),
    ):
        rc = _init_chezmoi_deploy.deploy_to_chezmoi(
            [Path("/x/a")],
            _init_chezmoi_deploy.ChezmoiDeployBehavior(
                command_label="skill init",
                commit_message="chore: regenerate skills via sase skill init",
                auto_commit_type="skills",
            ),
        )

    assert rc == 0
    assert seen_inside_lock == [
        "add",
        "diff",
        "commit",
        "rev-parse",
        "pull",
        "push",
        "chezmoi",
    ]
    assert "waiting for exclusive chezmoi deploy lock" in capsys.readouterr().out


def test_deploy_lock_path_uses_managed_tmpdir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Deploy locks stay inside the pytest-sandbox-aware managed temp root."""
    managed_lock_root = tmp_path / "managed-locks"
    calls: list[tuple[str, ...]] = []

    def _managed_tmpdir(*parts: str) -> str:
        calls.append(parts)
        managed_lock_root.mkdir()
        return str(managed_lock_root)

    monkeypatch.setattr(
        _init_chezmoi_deploy,
        "get_sase_managed_tmpdir",
        _managed_tmpdir,
    )

    lock_path = _init_chezmoi_deploy._chezmoi_deploy_lock_path(tmp_path / "repo")

    assert calls == [("chezmoi-deploy-locks",)]
    assert lock_path.parent == managed_lock_root
    assert lock_path.suffix == ".lock"


def test_deploy_lock_timeout_returns_clear_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A busy deploy lock fails clearly instead of blocking forever."""
    captured: list[list[str]] = []

    @contextmanager
    def fake_locked_file(_path: Path, _flags: int, **_kwargs: Any):
        raise LockTimeoutError(Path("/tmp/held.lock"), 0.25)
        yield

    def handler(*a: Any, **kw: Any) -> MagicMock:
        cmd = a[0] if a else kw.get("cmd", [])
        captured.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch.object(_init_chezmoi_deploy, "locked_file", fake_locked_file),
        patch.object(_init_chezmoi_deploy.subprocess, "run", side_effect=handler),
    ):
        rc = _init_chezmoi_deploy.deploy_to_chezmoi(
            [Path("/x/a")],
            _init_chezmoi_deploy.ChezmoiDeployBehavior(
                command_label="skill init",
                commit_message="chore: regenerate skills via sase skill init",
                auto_commit_type="skills",
            ),
        )

    assert rc == 1
    assert len(captured) == 1
    assert "--show-toplevel" in captured[0]
    err = capsys.readouterr().err
    assert "timed out waiting for exclusive chezmoi deploy lock after 0.25s" in err
    assert "/tmp/held.lock" in err
