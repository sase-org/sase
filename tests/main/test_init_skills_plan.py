"""Tests for read-only ``sase init skills`` planning."""

from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

import pytest
import yaml  # type: ignore[import-untyped]

from sase.main import init_skills_handler
from sase.main import _init_skills_rendering as skills_rendering
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_registry import InitCommandSpec
from sase.markdown_width import MARKDOWN_PRINT_WIDTH
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


def _stub_claude_skill_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    names: tuple[str, ...],
) -> dict[str, Path]:
    xprompts = {
        name: init_skills_handler.XPrompt(
            name=name,
            content=f"{name} body\n",
            description=f"{name} description",
            skill=["claude"],
        )
        for name in names
    }
    monkeypatch.setattr(init_skills_handler, "load_xprompts_from_internal", lambda: {})
    monkeypatch.setattr(
        init_skills_handler, "get_all_xprompts", lambda project="": xprompts
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)
    return {name: _get_target_path("claude", name, use_chezmoi=False) for name in names}


def test_plan_missing_target_reports_create_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)

    plan = plan_init_skills(make_args(provider="claude"))

    assert [(action.operation, action.path) for action in plan.actions] == [
        ("create", target)
    ]
    assert isinstance(plan.actions[0].new_content, str)
    assert plan.actions[0].new_content.endswith("\nbody\n")
    assert "create 1 provider skill file" == plan.summary
    assert plan.warnings == (init_skills_handler._PRETTIER_WARNING,)
    assert not target.exists()
    assert not target.parent.exists()


@pytest.mark.parametrize(
    "render_result",
    [
        (None, "packaged SKILL.frame.template.md: template error: broken"),
        ("not frontmatter\n", None),
    ],
)
def test_broken_skill_frame_blocks_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    render_result: tuple[str | None, str | None],
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)
    monkeypatch.setattr(
        skills_rendering,
        "render_markdown_template",
        lambda **_kwargs: render_result,
    )

    plan = plan_init_skills(make_args(provider="claude"))

    assert plan.actions == ()
    assert any("SKILL.frame.template.md" in blocker for blocker in plan.blockers)
    assert run_init_skills(make_args(provider="claude")) == 1
    assert "SKILL.frame.template.md" in capsys.readouterr().err
    assert not target.exists()


def test_skill_frame_default_render_is_stable() -> None:
    rendered = skills_rendering._build_output("demo", "A demo skill.", "Body.\n")

    assert rendered.startswith("---\nname: demo\ndescription: A demo skill.\n---\n\n")
    assert rendered.endswith(
        '```bash\nsase skill use demo --reason "<one-line reason for using this '
        'skill>"\n```\n\nBody.\n'
    )
    # The audit directive is prose wrapped at the repo Markdown width, so match
    # it on collapsed whitespace rather than pinning where it breaks.
    assert (
        "Before doing anything else, run this command to record that you are "
        "using this skill:"
    ) in " ".join(rendered.split())
    assert (
        skills_rendering._build_output(
            "demo", "A demo skill.", "Body.\n", log_skill_use=False
        )
        == "---\nname: demo\ndescription: A demo skill.\n---\n\nBody.\n"
    )
    long_description = (
        "This is a deliberately long generated skill description that exceeds the "
        "repo Markdown prose width so the existing wrapped YAML serialization path "
        "is exercised without changing its output."
    )
    long_output = skills_rendering._build_output(
        "long", long_description, "Body.\n", log_skill_use=False
    )

    assert long_output.startswith("---\nname: long\ndescription:\n  ")
    assert long_output.endswith("---\n\nBody.\n")
    assert yaml.safe_load(long_output.split("---\n")[1])["description"] == (
        long_description
    )
    assert all(len(line) <= MARKDOWN_PRINT_WIDTH for line in long_output.split("\n"))
    colon_description = (
        "This is a deliberately long generated skill description whose YAML needs "
        "a block scalar because it contains a mapping-like value: linked repos and "
        "external repos must remain part of the description."
    )
    colon_output = skills_rendering._build_output(
        "colon", colon_description, "Body.\n", log_skill_use=False
    )
    assert "description: >-\n" in colon_output
    assert skills_rendering._validate_skill_frame(colon_output) is None
    assert skills_rendering._build_output(
        "multi", "First line.\nSecond line.", "Body.\n", log_skill_use=False
    ) == (
        "---\nname: multi\ndescription: |\n  First line.\n  Second line.\n"
        "---\n\nBody.\n"
    )


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
    assert plan.actions[0].new_content != "stale skill\n"
    assert plan.summary == "overwrite 1 provider skill file"


def test_plan_honors_provider_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_claude_skill_target(tmp_path, monkeypatch)

    plan = plan_init_skills(make_args(provider="codex"))

    assert plan.actions == ()
    assert plan.warnings == ()


def test_plan_unknown_provider_reports_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_claude_skill_target(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "_all_providers", lambda: ["claude"])

    plan = plan_init_skills(make_args(provider="not-a-provider"))

    assert plan.actions == ()
    assert plan.blockers == (
        "unknown provider 'not-a-provider'; registered providers: claude",
    )


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
            'sase skill use foo --reason "<one-line reason for using this skill>"'
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
        assert "sase skill use" not in target.content
        assert "body" in target.content


def test_packaged_skills_respect_log_skill_use_flag() -> None:
    """Packaged unaudited skills omit the directive; other skills keep it."""
    from sase.xprompt.loader import (
        get_sase_package_xprompts_dir,
        load_xprompt_from_file,
    )

    skills_dir = get_sase_package_xprompts_dir() / "skills"
    plan_xp = load_xprompt_from_file(skills_dir / "sase_plan.md")
    memory_xp = load_xprompt_from_file(skills_dir / "sase_memory_read.md")
    repo_xp = load_xprompt_from_file(skills_dir / "sase_repo.md")
    project_xp = load_xprompt_from_file(skills_dir / "sase_project.md")
    artifact_file_xp = load_xprompt_from_file(skills_dir / "sase_artifact_file.md")
    assert plan_xp is not None
    assert memory_xp is not None
    assert repo_xp is not None
    assert project_xp is not None
    assert artifact_file_xp is not None

    assert plan_xp.log_skill_use is False
    assert memory_xp.log_skill_use is False
    assert repo_xp.log_skill_use is False
    assert project_xp.log_skill_use is True
    assert artifact_file_xp.log_skill_use is True

    targets = init_skills_handler.render_skill_targets(
        [plan_xp, memory_xp, repo_xp, project_xp, artifact_file_xp],
        provider_filter=None,
        use_chezmoi=False,
        use_prettier=False,
    )

    assert targets, "expected rendered targets for registered providers"
    for target in targets:
        if target.skill_name in {"sase_artifact_file", "sase_project"}:
            assert f"sase skill use {target.skill_name}" in target.content
        else:
            assert "sase skill use" not in target.content


def test_batch_formatter_failure_falls_back_per_unique_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase import file_references

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
    from sase import file_references

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


def test_check_mode_reports_drift_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)

    exit_code = run_init_skills(make_args(check=True, provider="claude"))

    assert exit_code == 1
    assert not target.exists()


def test_unchanged_target_non_tty_is_quiet_and_not_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _stub_claude_skill_target(tmp_path, monkeypatch)

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
    _stub_claude_skill_target(tmp_path, monkeypatch)
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
