"""Tests for generated ``sase init skills`` Markdown formatting."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import handle_init_skills_command
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
        "foo": XPrompt(name="foo", content="body\n", description="x", skill=["claude"]),
        "bar": XPrompt(name="bar", content="body\n", description="y", skill=["claude"]),
    }
    monkeypatch.setattr(init_skills_handler, "load_xprompts_from_internal", lambda: {})
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
