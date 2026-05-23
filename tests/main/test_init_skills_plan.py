"""Tests for read-only ``sase init skills`` planning."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.main import init_skills_handler
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_registry import InitCommandSpec
from sase.main.init_skills_handler import (
    _get_target_path,
    plan_init_skills,
    run_init_skills,
)
from tests.main.init_skills_handler_helpers import (
    make_args,
    stub_skill_source,
    stub_under_wrapped_skill,
)


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _onboarding_args() -> argparse.Namespace:
    return argparse.Namespace(
        command="init",
        init_subcommand=None,
        yes=False,
        check=False,
    )


def _stub_claude_skill_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    stub_skill_source(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)
    return _get_target_path("claude", "foo", use_chezmoi=False)


def test_plan_missing_target_reports_create_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)

    plan = plan_init_skills(make_args(provider="claude"))

    assert [(action.operation, action.path) for action in plan.actions] == [
        ("create", target)
    ]
    assert "create 1 provider skill file" == plan.summary
    assert not target.exists()
    assert not target.parent.exists()


def test_plan_identical_rendered_target_reports_no_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)

    assert run_init_skills(make_args(provider="claude")) == 0
    capsys.readouterr()

    plan = plan_init_skills(make_args(provider="claude"))

    assert target.exists()
    assert plan.actions == ()
    assert plan.summary == "provider skill files are current"


def test_plan_differing_target_reports_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)
    target.parent.mkdir(parents=True)
    target.write_text("stale skill\n", encoding="utf-8")

    plan = plan_init_skills(make_args(provider="claude"))

    assert [(action.operation, action.path) for action in plan.actions] == [
        ("overwrite", target)
    ]
    assert plan.summary == "overwrite 1 provider skill file"


def test_plan_honors_provider_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_claude_skill_target(tmp_path, monkeypatch)

    plan = plan_init_skills(make_args(provider="codex"))

    assert plan.actions == ()
    assert plan.warnings == ()


def test_prettier_present_plan_and_apply_bytes_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub_under_wrapped_skill(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        init_skills_handler.shutil,
        "which",
        lambda _: "/usr/bin/prettier",
    )

    from sase.gemini_wrapper import file_references

    marker = "<!-- formatted by test -->\n"
    monkeypatch.setattr(
        file_references,
        "format_with_prettier",
        lambda text: text + marker,
    )
    target = _get_target_path("claude", "foo", use_chezmoi=False)

    assert run_init_skills(make_args(provider="claude")) == 0
    capsys.readouterr()

    assert target.read_text(encoding="utf-8").endswith(marker)
    assert plan_init_skills(make_args(provider="claude")).actions == ()


def test_non_tty_explicit_init_skills_skips_existing_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)
    target.parent.mkdir(parents=True)
    target.write_text("keep me\n", encoding="utf-8")
    monkeypatch.setattr(init_skills_handler.sys, "stdin", StringIO())

    exit_code = run_init_skills(make_args(force=False, provider="claude"))

    assert exit_code == 0
    assert target.read_text(encoding="utf-8") == "keep me\n"
    err = capsys.readouterr().err
    assert "exists, skipping (not a TTY; use -f to force)" in err


def test_onboarding_confirmed_skills_apply_uses_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)
    target.parent.mkdir(parents=True)
    target.write_text("stale skill\n", encoding="utf-8")
    prompt_mock = MagicMock(side_effect=AssertionError("unexpected file prompt"))
    monkeypatch.setattr(init_skills_handler, "_prompt_overwrite", prompt_mock)

    spec = InitCommandSpec(
        name="skills",
        label="Skills",
        plan=plan_init_skills,
        run=run_init_skills,
    )
    exit_code = run_init_onboarding(
        _onboarding_args(),
        specs=(spec,),
        stdin=_TtyStringIO(),
        input_func=lambda prompt: "yes",
    )

    assert exit_code == 0
    assert target.read_text(encoding="utf-8") != "stale skill\n"
    prompt_mock.assert_not_called()
