"""Tests for read-only ``sase init skills`` planning."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
import subprocess
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
    assert plan.warnings == (init_skills_handler._PRETTIER_WARNING,)
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

    marker = "<!-- formatted by test -->\n"
    monkeypatch.setattr(
        init_skills_handler,
        "_format_unique_skill_outputs_batch",
        lambda outputs: [text + marker for text in outputs],
    )
    target = _get_target_path("claude", "foo", use_chezmoi=False)

    assert run_init_skills(make_args(provider="claude")) == 0
    capsys.readouterr()

    assert target.read_text(encoding="utf-8").endswith(marker)
    assert plan_init_skills(make_args(provider="claude")).actions == ()


def test_duplicate_raw_outputs_are_formatted_once_and_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompt = init_skills_handler.XPrompt(
        name="foo",
        content="body\n",
        description="a test skill",
        skill=["claude"],
    )
    target_paths = [
        tmp_path / "one" / "SKILL.md",
        tmp_path / "two" / "SKILL.md",
    ]
    monkeypatch.setattr(
        init_skills_handler,
        "_get_target_paths",
        lambda provider, skill_name, use_chezmoi: target_paths,
    )
    calls: list[tuple[str, ...]] = []

    def fake_batch(outputs: list[str]) -> list[str]:
        calls.append(tuple(outputs))
        return [outputs[0] + "formatted\n"]

    monkeypatch.setattr(
        init_skills_handler,
        "_format_unique_skill_outputs_batch",
        fake_batch,
    )

    targets = init_skills_handler.render_skill_targets(
        [xprompt],
        provider_filter="claude",
        use_chezmoi=False,
        use_prettier=True,
    )

    assert len(targets) == 2
    assert [target.path for target in targets] == target_paths
    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert targets[0].content == targets[1].content
    assert targets[0].content.endswith("formatted\n")


def test_rendered_skill_targets_include_audit_directive_for_each_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xprompt = init_skills_handler.XPrompt(
        name="foo",
        content="body\n",
        description="a test skill",
        skill=["claude", "codex"],
    )
    monkeypatch.setattr(
        init_skills_handler,
        "_all_providers",
        lambda: ["claude", "codex"],
    )
    monkeypatch.setattr(init_skills_handler, "_provider_context", lambda _provider: {})
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    targets = init_skills_handler.render_skill_targets(
        [xprompt],
        provider_filter=None,
        use_chezmoi=False,
        use_prettier=False,
    )

    assert {target.provider for target in targets} == {"claude", "codex"}
    for target in targets:
        content = target.content
        directive = (
            'sase skills log foo --reason "<one-line reason for using this skill>"'
        )
        assert directive in content
        assert content.index(directive) < content.index("body")


def test_rendered_skill_targets_omit_audit_directive_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A skill with ``log_skill_use=False`` renders without the audit directive."""
    xprompt = init_skills_handler.XPrompt(
        name="foo",
        content="body\n",
        description="a test skill",
        skill=["claude"],
        log_skill_use=False,
    )
    monkeypatch.setattr(init_skills_handler, "_all_providers", lambda: ["claude"])
    monkeypatch.setattr(init_skills_handler, "_provider_context", lambda _provider: {})
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    targets = init_skills_handler.render_skill_targets(
        [xprompt],
        provider_filter=None,
        use_chezmoi=False,
        use_prettier=False,
    )

    assert targets
    for target in targets:
        assert "sase skills log" not in target.content
        assert "body" in target.content


def test_packaged_skills_respect_log_skill_use_flag() -> None:
    """Packaged sase_plan/sase_memory_read omit the directive; others keep it."""
    from sase.xprompt.loader import (
        get_sase_package_xprompts_dir,
        load_xprompt_from_file,
    )

    skills_dir = get_sase_package_xprompts_dir() / "skills"
    plan_xp = load_xprompt_from_file(skills_dir / "sase_plan.md")
    memory_xp = load_xprompt_from_file(skills_dir / "sase_memory_read.md")
    artifact_xp = load_xprompt_from_file(skills_dir / "sase_artifact.md")
    assert plan_xp is not None
    assert memory_xp is not None
    assert artifact_xp is not None

    assert plan_xp.log_skill_use is False
    assert memory_xp.log_skill_use is False
    assert artifact_xp.log_skill_use is True

    targets = init_skills_handler.render_skill_targets(
        [plan_xp, memory_xp, artifact_xp],
        provider_filter=None,
        use_chezmoi=False,
        use_prettier=False,
    )

    assert targets, "expected rendered targets for registered providers"
    for target in targets:
        if target.skill_name == "sase_artifact":
            assert "sase skills log sase_artifact" in target.content
        else:
            assert "sase skills log" not in target.content


def test_batch_formatter_failure_falls_back_per_unique_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.gemini_wrapper import file_references

    def fail_batch(outputs: list[str]) -> list[str]:
        raise subprocess.CalledProcessError(1, ["prettier"])

    single_calls: list[str] = []

    def fake_single(text: str) -> str:
        single_calls.append(text)
        return f"single:{text}"

    monkeypatch.setattr(
        init_skills_handler,
        "_format_unique_skill_outputs_batch",
        fail_batch,
    )
    monkeypatch.setattr(file_references, "format_with_prettier", fake_single)

    formatted = init_skills_handler._format_skill_outputs(
        ["same\n", "same\n", "other\n"],
        use_prettier=True,
    )

    assert formatted == ["single:same\n", "single:same\n", "single:other\n"]
    assert single_calls == ["same\n", "other\n"]


def test_batch_formatter_timeout_falls_back_per_unique_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung prettier must degrade like a failed one, not hang the caller."""
    from sase.gemini_wrapper import file_references

    def hang_batch(outputs: list[str]) -> list[str]:
        raise subprocess.TimeoutExpired(["prettier"], 10.0)

    monkeypatch.setattr(
        init_skills_handler,
        "_format_unique_skill_outputs_batch",
        hang_batch,
    )
    monkeypatch.setattr(file_references, "format_with_prettier", lambda text: text)

    formatted = init_skills_handler._format_skill_outputs(
        ["body\n"],
        use_prettier=True,
    )

    assert formatted == ["body\n"]


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
