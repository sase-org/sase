"""Tests for generated ``sase init skills`` Markdown formatting."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import (
    _get_target_path,
    handle_init_skills_command,
    plan_init_skills,
    run_init_skills,
)
from sase.markdown_width import prettier_markdown_argv
from sase.xprompt.models import XPrompt
from tests.main.init_skills_handler_helpers import (
    make_args,
    stub_under_wrapped_skill,
)


@pytest.mark.skipif(shutil.which("prettier") is None, reason="prettier not installed")
def test_handler_output_passes_prettier_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generated SKILL.md must pass `prettier --check` with the chezmoi CI args."""
    stub_under_wrapped_skill(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    with pytest.raises(SystemExit):
        handle_init_skills_command(make_args())

    written = tmp_path / "home" / ".claude" / "skills" / "foo" / "SKILL.md"
    assert written.exists()

    result = subprocess.run(
        [
            *prettier_markdown_argv(),
            "--check",
        ],
        input=written.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prettier --check failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


@pytest.mark.skipif(shutil.which("prettier") is None, reason="prettier not installed")
def test_handler_output_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running init skills twice produces byte-identical output the second time."""
    stub_under_wrapped_skill(tmp_path, monkeypatch)
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    with pytest.raises(SystemExit):
        handle_init_skills_command(make_args())

    written = tmp_path / "home" / ".claude" / "skills" / "foo" / "SKILL.md"
    first = written.read_text(encoding="utf-8")

    with pytest.raises(SystemExit):
        handle_init_skills_command(make_args())

    second = written.read_text(encoding="utf-8")
    assert first == second


def test_handler_warns_once_when_prettier_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When prettier is absent, emit one warning per invocation, not per skill."""
    xprompts = {
        "skill/foo": XPrompt(
            name="skill/foo",
            content="body\n",
            description="x",
            skill=["claude"],
            skill_name="foo",
        ),
        "skill/bar": XPrompt(
            name="skill/bar",
            content="body\n",
            description="y",
            skill=["claude"],
            skill_name="bar",
        ),
    }
    monkeypatch.setattr(init_skills_handler, "load_skills_from_package", lambda: {})
    monkeypatch.setattr(
        init_skills_handler, "get_all_xprompts", lambda project="": xprompts
    )
    monkeypatch.setattr(init_skills_handler, "get_use_chezmoi", lambda: False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(init_skills_handler.shutil, "which", lambda _: None)

    with pytest.raises(SystemExit):
        handle_init_skills_command(make_args())

    err = capsys.readouterr().err
    assert err.count("prettier not found") == 1


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
        name="skill/foo",
        content="body\n",
        description="a test skill",
        skill=["claude"],
        skill_name="foo",
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
