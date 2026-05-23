"""Tests for bare ``sase init`` onboarding."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from io import StringIO
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

from sase.main import _init_chezmoi_deploy
from sase.main._init_chezmoi_deploy import defer_chezmoi_paths
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_registry import InitCommandSpec, iter_init_command_specs
from sase.main.parser import create_parser
from tests.main.init_skills_handler_helpers import git_cmd_handler


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _args(*, yes: bool = False, check: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        command="init",
        init_subcommand=None,
        yes=yes,
        check=check,
    )


def _plan(
    command: str,
    *,
    actions: tuple[InitAction, ...] = (),
    summary: str = "",
    warnings: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
) -> InitPlan:
    return InitPlan(
        command=command,
        label=f"Init {command}",
        summary=summary,
        actions=actions,
        warnings=warnings,
        blockers=blockers,
    )


def _changed_action(path: str = "memory/short/sase.md") -> InitAction:
    return InitAction(Path(path), "update", "changed")


def _spec(
    name: str,
    plan: InitPlan,
    calls: list[str],
    args_seen: list[argparse.Namespace] | None = None,
    exit_code: int = 0,
) -> InitCommandSpec:
    def _run(args: argparse.Namespace) -> int:
        calls.append(name)
        if args_seen is not None:
            args_seen.append(args)
        return exit_code

    return InitCommandSpec(
        name=name,
        label=plan.label,
        plan=lambda args: plan,
        run=_run,
    )


def _reject_prompt(prompt: str) -> str:
    raise AssertionError(f"unexpected prompt: {prompt}")


def test_parser_accepts_bare_init_modes() -> None:
    parser = create_parser()

    init_args = parser.parse_args(["init"])
    assert init_args.command == "init"
    assert init_args.init_subcommand is None
    assert init_args.yes is False
    assert init_args.check is False

    yes_args = parser.parse_args(["init", "--yes"])
    assert yes_args.init_subcommand is None
    assert yes_args.yes is True

    check_args = parser.parse_args(["init", "--check"])
    assert check_args.init_subcommand is None
    assert check_args.check is True

    short_check_args = parser.parse_args(["init", "-c"])
    assert short_check_args.init_subcommand is None
    assert short_check_args.check is True


def test_init_help_lists_existing_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["init", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "memory" in out
    assert "sdd" in out
    assert "skills" in out
    assert "-c, --check" in out
    assert "Advanced deploy controls live on explicit subcommands" in out


def test_registry_order_is_memory_sdd_skills() -> None:
    assert tuple(spec.name for spec in iter_init_command_specs()) == (
        "memory",
        "sdd",
        "skills",
    )


def test_noop_plans_print_initialized_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory"), calls),
        _spec("sdd", _plan("sdd"), calls),
        _spec("skills", _plan("skills"), calls),
    )

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "SASE is initialized. No init subcommands need to run." in out
    assert "Checked: memory, sdd, skills." in out


def test_interactive_prompt_runs_only_confirmed_plan(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    responses = iter(["yes", "n"])
    specs = (
        _spec(
            "memory",
            _plan(
                "memory",
                actions=(_changed_action(),),
                summary="update 2 memory files",
            ),
            calls,
        ),
        _spec(
            "skills",
            _plan(
                "skills",
                actions=(_changed_action(".codex/skills/foo/SKILL.md"),),
                summary="write 5 provider skill files",
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=lambda prompt: next(responses),
    )

    assert exit_code == 0
    assert calls == ["memory"]
    out = capsys.readouterr().out
    assert "Needs attention:" in out
    assert "init memory" in out
    assert "init skills" in out


def test_full_drift_prompt_order_all_three_plans() -> None:
    calls: list[str] = []
    prompts: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan("memory", actions=(_changed_action(),), summary="update memory"),
            calls,
        ),
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(_changed_action("sdd/README.md"),),
                summary="update SDD files",
            ),
            calls,
        ),
        _spec(
            "skills",
            _plan(
                "skills",
                actions=(_changed_action(".codex/skills/foo/SKILL.md"),),
                summary="overwrite skills",
            ),
            calls,
        ),
    )

    def _answer(prompt: str) -> str:
        prompts.append(prompt)
        return "yes"

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_answer,
    )

    assert exit_code == 0
    assert calls == ["memory", "sdd", "skills"]
    assert [prompt.split(" now?", maxsplit=1)[0] for prompt in prompts] == [
        "Run `sase init memory`",
        "Run `sase init sdd`",
        "Run `sase init skills --force`",
    ]


def test_non_tty_drift_without_yes_prints_summary_and_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan(
                "memory",
                actions=(_changed_action(),),
                summary="update 2 memory files",
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == []
    out = capsys.readouterr().out
    assert "Needs attention:" in out
    assert "update 2 memory files" in out
    assert "Run `sase init --yes` to apply these changes." in out


def test_check_mode_reports_drift_without_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "sdd",
            _plan(
                "sdd",
                actions=(_changed_action("sdd/README.md"),),
                summary="update SDD README files",
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(check=True),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == []
    out = capsys.readouterr().out
    assert "Needs attention:" in out
    assert "update SDD README files" in out


def test_check_mode_does_not_apply_later_changed_plans() -> None:
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory", actions=(_changed_action(),)), calls),
        _spec(
            "skills",
            _plan("skills", actions=(_changed_action(".codex/skills/foo/SKILL.md"),)),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(check=True),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == []


def test_blocker_prints_and_exits_1_without_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "memory",
            _plan(
                "memory",
                actions=(_changed_action(),),
                summary="update generated memory",
                blockers=("invalid sibling repo config",),
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

    assert exit_code == 1
    assert calls == []
    out = capsys.readouterr().out
    assert "Blockers:" in out
    assert "invalid sibling repo config" in out


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


def test_yes_runs_one_deferred_chezmoi_deploy_after_selected_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _deferred_run(
        name: str,
        path: Path,
        *,
        apply_force: bool = False,
    ) -> Callable[[argparse.Namespace], int]:
        def _run(args: argparse.Namespace) -> int:
            calls.append(name)
            assert defer_chezmoi_paths([path], apply_force=apply_force) is True
            return 0

        return _run

    specs = (
        InitCommandSpec(
            name="memory",
            label="Memory",
            plan=lambda args: _plan(
                "memory",
                actions=(InitAction(Path("memory/short/sase.md"), "update"),),
                summary="update memory",
            ),
            run=_deferred_run(
                "memory",
                Path("/home/x/chezmoi/home/memory/short/sase.md"),
                apply_force=True,
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
        "pull",
        "push",
        "chezmoi",
    ]
    commit = next(cmd for cmd in commands if "commit" in cmd and "-m" in cmd)
    assert commit[commit.index("-m") + 1] == "chore: run sase init"
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


def test_needs_attention_output_snapshot_caps_path_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec("sdd", _plan("sdd", summary="SDD current"), calls),
        _spec(
            "memory",
            _plan(
                "memory",
                summary="refresh 4 memory files",
                actions=(
                    InitAction(
                        Path("memory/short/sase.md"), "update", "project memory"
                    ),
                    InitAction(Path("AGENTS.md"), "create", "project instructions"),
                    InitAction(Path("CLAUDE.md"), "overwrite", "provider shim"),
                    InitAction(Path("GEMINI.md"), "overwrite", "provider shim"),
                ),
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(check=True),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert capsys.readouterr().out == (
        "SASE initialization check\n"
        "\n"
        "Up to date:\n"
        "  ok   init sdd     SDD current\n"
        "\n"
        "Needs attention:\n"
        "  run  init memory  refresh 4 memory files\n"
        "    - update    memory/short/sase.md  project memory\n"
        "    - create    AGENTS.md  project instructions\n"
        "    - overwrite CLAUDE.md  provider shim\n"
        "    ... 1 more action\n"
    )


def test_warning_without_changes_is_visible_and_successful(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec(
            "skills",
            _plan(
                "skills",
                summary="provider skill files are current",
                warnings=("prettier not found",),
            ),
            calls,
        ),
    )

    exit_code = run_init_onboarding(
        _args(),
        specs=specs,
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Up to date:" in out
    assert "Warnings:" in out
    assert "init skills: prettier not found" in out


def test_cli_main_dispatches_bare_init(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import entry, init_onboarding

    calls: list[str] = []
    specs = (_spec("memory", _plan("memory"), calls),)
    monkeypatch.setattr(init_onboarding, "iter_init_command_specs", lambda: specs)
    monkeypatch.setattr(sys, "argv", ["sase", "init"])

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    assert calls == []
    assert (
        "SASE is initialized. No init subcommands need to run."
        in capsys.readouterr().out
    )
