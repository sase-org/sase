"""Tests for applying ``sase init skills`` plans to disk."""

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
    stub_claude_skill_target,
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


def _stub_claude_skill_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    names: tuple[str, ...],
) -> dict[str, Path]:
    xprompts = {
        f"skills/{name}": init_skills_handler.XPrompt(
            name=f"skills/{name}",
            content=f"{name} body\n",
            description=f"{name} description",
            skill=["claude"],
            skill_name=name,
        )
        for name in names
    }
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler, "get_all_xprompts", lambda project="": xprompts
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)
    return {name: _get_target_path("claude", name, use_chezmoi=False) for name in names}


def test_non_tty_explicit_init_skills_skips_existing_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)
    target.parent.mkdir(parents=True)
    target.write_text("keep me\n", encoding="utf-8")
    monkeypatch.setattr(init_skills_handler.sys, "stdin", StringIO())

    exit_code = run_init_skills(make_args(force=False, provider="claude"))

    assert exit_code == 0
    assert target.read_text(encoding="utf-8") == "keep me\n"
    err = capsys.readouterr().err
    assert "exists, skipping (not a TTY; use -f to force)" in err


def test_check_mode_reports_drift_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)

    exit_code = run_init_skills(make_args(check=True, provider="claude"))

    assert exit_code == 1
    assert not target.exists()


def test_unchanged_target_non_tty_is_quiet_and_not_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)

    assert run_init_skills(make_args(provider="claude")) == 0
    capsys.readouterr()
    first = target.read_text(encoding="utf-8")
    monkeypatch.setattr(init_skills_handler.sys, "stdin", StringIO())

    assert run_init_skills(make_args(force=False, provider="claude")) == 0

    captured = capsys.readouterr()
    assert target.read_text(encoding="utf-8") == first
    assert "exists, skipping" not in captured.err
    assert "Written: 0, Skipped: 0, Unchanged: 1" in captured.out


def test_force_rewrites_only_drifted_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    targets = _stub_claude_skill_targets(tmp_path, monkeypatch, ("current", "stale"))

    assert run_init_skills(make_args(provider="claude")) == 0
    capsys.readouterr()
    current_content = targets["current"].read_text(encoding="utf-8")
    targets["stale"].write_text("stale skill\n", encoding="utf-8")

    assert run_init_skills(make_args(force=True, provider="claude")) == 0

    out = capsys.readouterr().out
    assert str(targets["stale"]) in out
    assert str(targets["current"]) not in out
    assert targets["current"].read_text(encoding="utf-8") == current_content
    assert targets["stale"].read_text(encoding="utf-8") != "stale skill\n"
    assert "Written: 1, Skipped: 0, Unchanged: 1" in out


def test_dry_run_lists_only_real_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    targets = _stub_claude_skill_targets(tmp_path, monkeypatch, ("current", "stale"))

    assert run_init_skills(make_args(provider="claude")) == 0
    capsys.readouterr()
    targets["stale"].write_text("stale skill\n", encoding="utf-8")

    assert run_init_skills(make_args(dry_run=True, provider="claude")) == 0

    out = capsys.readouterr().out
    assert f"overwrite: {targets['stale']}" in out
    assert str(targets["current"]) not in out


def test_overwrite_prompt_d_uses_shared_diff_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "SKILL.md"
    target.write_text("old body\n", encoding="utf-8")
    answers = iter(["d", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert init_skills_handler._prompt_overwrite(target, "new body\n") is False

    out = capsys.readouterr().out
    assert "@@ -1 +1 @@" in out
    assert "-old body" in out
    assert "+new body" in out


def test_unknown_provider_errors_at_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub_claude_skill_target(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "_all_providers", lambda: ["claude"])

    exit_code = run_init_skills(make_args(provider="not-a-provider"))

    assert exit_code == 2
    assert (
        "skill init: unknown provider 'not-a-provider'; registered providers: claude"
        in capsys.readouterr().err
    )


def test_onboarding_confirmed_skills_apply_uses_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)
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
