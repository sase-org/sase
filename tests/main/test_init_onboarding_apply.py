"""Apply tests for bare ``sase init`` onboarding."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.main import _init_chezmoi_deploy
from sase.main._init_chezmoi_deploy import defer_chezmoi_paths
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_registry import InitCommandSpec
from tests.main.init_onboarding_helpers import (
    _args,
    _changed_action,
    _plan,
    _reject_prompt,
    _spec,
)
from tests.main.init_skills_handler_helpers import git_cmd_handler


def test_yes_runs_all_changed_specs_in_order() -> None:
    calls: list[str] = []
    args_seen: list[argparse.Namespace] = []
    specs = (
        _spec(
            "memory",
            _plan("memory", actions=(_changed_action(),), summary="update memory"),
            calls,
            args_seen,
        ),
        _spec(
            "skills",
            _plan(
                "skills",
                actions=(_changed_action(".codex/skills/foo/SKILL.md"),),
                summary="overwrite skills",
            ),
            calls,
            args_seen,
        ),
    )

    exit_code = run_init_onboarding(
        _args(yes=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["memory", "skills"]
    assert [seen.init_subcommand for seen in args_seen] == ["memory", "skills"]
    assert args_seen[1].force is True


def test_enable_project_memory_writes_management_marker_before_all_planning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    monkeypatch.chdir(project_root)
    calls: list[str] = []

    def plan_memory(args: argparse.Namespace) -> InitPlan:
        assert (project_root / "sase" / "sase.yml").read_text(encoding="utf-8") == (
            "is_sase_managed: true\n"
        )
        return _plan(
            "memory",
            actions=(_changed_action("sase/sase.yml"),),
            summary="mark repository as SASE-managed",
        )

    def plan_sdd(args: argparse.Namespace) -> InitPlan:
        assert (project_root / "sase" / "sase.yml").read_text(encoding="utf-8") == (
            "is_sase_managed: true\n"
        )
        return _plan(
            "sdd",
            actions=(_changed_action(".sase/sdd/README.md"),),
            summary="initialize SDD",
        )

    specs = (
        InitCommandSpec(
            name="memory",
            label="Memory",
            plan=plan_memory,
            run=lambda args: calls.append("memory") or 0,
        ),
        InitCommandSpec(
            name="sdd",
            label="SDD",
            plan=plan_sdd,
            run=lambda args: calls.append("sdd") or 0,
        ),
    )

    exit_code = run_init_onboarding(
        _args(yes=True, enable_project_memory=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["memory", "sdd"]


def test_yes_runs_one_deferred_chezmoi_deploy_after_selected_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _deferred_run(
        name: str,
        path: Path,
    ) -> Callable[[argparse.Namespace], int]:
        def _run(args: argparse.Namespace) -> int:
            calls.append(name)
            assert defer_chezmoi_paths([path]) is True
            return 0

        return _run

    specs = (
        InitCommandSpec(
            name="memory",
            label="Memory",
            plan=lambda args: _plan(
                "memory",
                actions=(InitAction(Path("memory/sase.md"), "update"),),
                summary="update memory",
            ),
            run=_deferred_run(
                "memory",
                Path("/home/x/chezmoi/home/memory/sase.md"),
            ),
        ),
        InitCommandSpec(
            name="skills",
            label="Skills",
            plan=lambda args: _plan(
                "skills",
                actions=(InitAction(Path(".claude/skills/foo/SKILL.md"), "update"),),
                summary="update skills",
            ),
            run=_deferred_run(
                "skills",
                Path("/home/x/chezmoi/home/dot_claude/skills/foo/SKILL.md"),
            ),
        ),
    )
    run_mock = MagicMock(side_effect=git_cmd_handler())
    monkeypatch.setattr(_init_chezmoi_deploy.subprocess, "run", run_mock)

    exit_code = run_init_onboarding(
        _args(yes=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["memory", "skills"]
    commands = [call.args[0] for call in run_mock.call_args_list]
    verbs = [
        cmd[cmd.index("git") + 3] if cmd[0] == "git" else "chezmoi" for cmd in commands
    ]
    assert verbs == [
        "rev-parse",
        "add",
        "add",
        "diff",
        "commit",
        "rev-parse",
        "pull",
        "push",
        "chezmoi",
    ]
    commit = next(cmd for cmd in commands if "commit" in cmd and "-m" in cmd)
    assert commit[commit.index("-m") + 1] == "chore: run sase init\n\nSASE_TYPE=init"
    apply = commands[-1]
    assert apply == ["chezmoi", "apply", "--force"]


def test_yes_stops_after_apply_failure_and_reports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan("memory", actions=(_changed_action(),), summary="update memory"),
            calls,
            exit_code=7,
        ),
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(_changed_action("sdd/README.md"),),
                summary="update SDD",
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(yes=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 7
    assert calls == ["memory"]
    assert "init memory failed with exit code 7." in capsys.readouterr().out
