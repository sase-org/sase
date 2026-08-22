"""Tests for applying ``sase init skills`` plans to disk."""

from __future__ import annotations

import argparse
from io import StringIO
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.main import init_skills_handler
from sase.main._init_skills_manifest import (
    SKILLS_MANIFEST_FILENAME,
    ManagedSkillFile,
    _SkillDeployManifest,
)
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_registry import InitCommandSpec
from sase.main.init_skills_handler import (
    _get_target_path,
    plan_init_skills,
    run_init_skills,
)
from tests.main.init_skills_handler_helpers import (
    make_args,
    stub_manifest_git,
    stub_claude_skill_target,
)


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
    assert "exists, skipping (not a TTY; use -f to force or -y to answer yes)" in err


def test_non_tty_init_skills_yes_overwrites_existing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = stub_claude_skill_target(tmp_path, monkeypatch)
    target.parent.mkdir(parents=True)
    target.write_text("replace me\n", encoding="utf-8")
    monkeypatch.setattr(init_skills_handler.sys, "stdin", StringIO())

    exit_code = run_init_skills(make_args(force=False, yes=True, provider="claude"))

    assert exit_code == 0
    assert target.read_text(encoding="utf-8") != "replace me\n"


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


def _write_retired_manifest_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    home_root = tmp_path / "home"
    source = chezmoi_home / "dot_claude" / "skills" / "sase_old" / "SKILL.md"
    live = home_root / ".claude" / "skills" / "sase_old" / "SKILL.md"
    _write(source, "retired source\n")
    _write(live, "retired live\n")
    manifest = chezmoi_home / SKILLS_MANIFEST_FILENAME
    manifest.write_text(
        _SkillDeployManifest(
            source_commit="2" * 40,
            xprompt_set_sha256="old-hash",
            deployed_at="2026-07-28T12:00:00Z",
            managed_files=(
                ManagedSkillFile(
                    provider="claude",
                    skill_name="sase_old",
                    source_relpath="dot_claude/skills/sase_old/SKILL.md",
                    home_relpath=".claude/skills/sase_old/SKILL.md",
                    state="active",
                ),
            ),
        ).to_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler, "skill_source_integrity_error", lambda: None
    )
    monkeypatch.setattr(init_skills_handler, "get_all_xprompts", lambda project="": {})
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: True)
    monkeypatch.setattr(init_skills_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)
    monkeypatch.setattr(Path, "home", lambda: home_root)
    stub_manifest_git(monkeypatch, tmp_path, incoming="2" * 40, ancestors=set())
    return source, live, manifest


def test_force_deletes_retired_source_and_defers_live_target_to_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, live, manifest = _write_retired_manifest_fixture(tmp_path, monkeypatch)
    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    exit_code = run_init_skills(make_args(force=True))

    assert exit_code == 0
    assert not source.exists()
    assert not source.parent.exists()
    assert live.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["managed_files"][0]["state"] == "retired"
    deploy_mock.assert_called_once()
    assert deploy_mock.call_args.kwargs["delete_targets"] == [live]


def test_non_tty_retired_delete_is_skipped_and_manifest_remains_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, live, manifest = _write_retired_manifest_fixture(tmp_path, monkeypatch)
    before = manifest.read_text(encoding="utf-8")
    monkeypatch.setattr(init_skills_handler.sys, "stdin", StringIO())
    deploy_mock = MagicMock(return_value=0)
    monkeypatch.setattr(init_skills_handler, "_deploy_to_chezmoi", deploy_mock)

    exit_code = run_init_skills(make_args(force=False, yes=False))

    assert exit_code == 0
    assert source.exists()
    assert live.exists()
    assert manifest.read_text(encoding="utf-8") == before
    deploy_mock.assert_not_called()


def test_dry_run_reports_retired_delete_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, live, _manifest = _write_retired_manifest_fixture(tmp_path, monkeypatch)

    exit_code = run_init_skills(make_args(dry_run=True))

    assert exit_code == 0
    assert source.exists()
    assert live.exists()
    out = capsys.readouterr().out
    assert f"delete: {source} -> {live}" in out
