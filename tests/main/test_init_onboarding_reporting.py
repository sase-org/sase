"""Status and reporting tests for bare ``sase init`` onboarding."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_plan import InitAction
from tests.main.init_onboarding_helpers import (
    _TtyStringIO,
    _args,
    _changed_action,
    _plan,
    _reject_prompt,
    _spec,
)


def test_noop_plans_print_initialized_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory"), calls),
        _spec("repo", _plan("repo"), calls),
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
    assert "Checked: memory, repo, skills." in out


def test_bare_init_check_skips_repo_outside_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory", summary="memory current"), calls),
        _spec(
            "repo",
            _plan(
                "repo",
                actions=(_changed_action("sase.yml"),),
                summary="create repository wiring",
            ),
            calls,
        ),
        _spec("skills", _plan("skills", summary="skills current"), calls),
    )
    monkeypatch.setattr(init_onboarding, "iter_init_command_specs", lambda: specs)

    exit_code = run_init_onboarding(
        _args(check=True),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Checked: memory, skills." in out
    assert "init repo" not in out
    assert calls == []


def test_bare_init_check_includes_repo_inside_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import init_onboarding

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []
    specs = (
        _spec("memory", _plan("memory", summary="memory current"), calls),
        _spec(
            "repo",
            _plan(
                "repo",
                actions=(_changed_action("sase.yml"),),
                summary="create repository wiring",
            ),
            calls,
        ),
        _spec("skills", _plan("skills", summary="skills current"), calls),
    )
    monkeypatch.setattr(init_onboarding, "iter_init_command_specs", lambda: specs)

    exit_code = run_init_onboarding(
        _args(check=True),
        stdin=StringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "init repo" in out
    assert "create repository wiring" in out
    assert calls == []


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
            "repo",
            _plan(
                "repo",
                actions=(_changed_action("sase.yml"),),
                summary="update repository wiring",
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
    assert "update repository wiring" in out


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


def test_needs_attention_output_snapshot_lists_every_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    specs = (
        _spec("repo", _plan("repo", summary="Repos current"), calls),
        _spec(
            "memory",
            _plan(
                "memory",
                summary="refresh 4 memory files",
                actions=(
                    InitAction(Path("memory/sase.md"), "update", "project memory"),
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
        "  ok   init repo    Repos current\n"
        "\n"
        "Needs attention:\n"
        "  run  init memory  refresh 4 memory files\n"
        "       ~ update     memory/sase.md  –  project memory\n"
        "       + create     AGENTS.md       –  project instructions\n"
        "       ~ overwrite  CLAUDE.md       –  provider shim\n"
        "       ~ overwrite  GEMINI.md       –  provider shim\n"
    )


def test_check_diff_renders_full_diff_and_reports_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "README.md"
    target.write_text("before\n", encoding="utf-8")
    calls: list[str] = []
    specs = (
        _spec(
            "repo",
            _plan(
                "repo",
                actions=(InitAction(target, "update", "README", "after\n"),),
            ),
            calls,
        ),
    )

    assert (
        run_init_onboarding(
            _args(check=True, diff=True),
            specs=specs,
            stdin=StringIO(),
            input_func=_reject_prompt,
        )
        == 1
    )

    out = capsys.readouterr().out
    assert "-before" in out
    assert "+after" in out
    assert calls == []


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
