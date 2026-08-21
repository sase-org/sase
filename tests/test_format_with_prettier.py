"""Tests for the parameterized prose wrap width of format_with_prettier."""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.file_references import (
    format_agent_prompt_markdown,
    format_markdown_files_with_prettier,
    format_with_prettier,
)
from sase.markdown_width import markdown_print_width


def _fake_run_capturing(captured: list[list[str]]) -> Any:
    """Build a subprocess.run stand-in that records argv and echoes input."""

    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=kwargs["input"], stderr="")

    return _run


def test_format_with_prettier_default_uses_the_width_authority() -> None:
    """The default call wraps prose at the single resolved width."""
    captured: list[list[str]] = []
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=_fake_run_capturing(captured),
        ),
    ):
        format_with_prettier("some prose")

    assert captured, "prettier should have been invoked"
    assert f"--print-width={markdown_print_width()}" in captured[0]
    assert "--print-width=80" not in captured[0]


def test_agent_prompt_formatter_uses_default_width() -> None:
    """The named agent-prompt policy flows the declared width through to prettier."""
    captured: list[list[str]] = []
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=_fake_run_capturing(captured),
        ),
    ):
        format_agent_prompt_markdown("some prose")

    assert captured, "prettier should have been invoked"
    assert f"--print-width={markdown_print_width()}" in captured[0]
    assert "--print-width=80" not in captured[0]


def test_agent_prompt_formatter_matches_default_formatter_argv() -> None:
    """format_agent_prompt_markdown and format_with_prettier must agree on argv.

    This is the regression test for the original 80-vs-120 split: it fails
    loudly if a future change re-forks the prompt width without updating the
    published-artifact path.
    """
    captured: list[list[str]] = []
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=_fake_run_capturing(captured),
        ),
    ):
        format_agent_prompt_markdown("some prose")
        format_with_prettier("some prose")

    assert len(captured) == 2
    assert captured[0] == captured[1]


def test_format_with_prettier_missing_prettier_returns_text() -> None:
    """Fallback behavior is unchanged when prettier is unavailable."""
    with patch("sase.file_references.shutil.which", return_value=None):
        assert format_with_prettier("untouched", print_width=80) == "untouched"


def test_format_with_prettier_ignores_retired_disable_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retired ``SASE_DISABLE_PRETTIER`` alias is no longer an escape hatch."""
    monkeypatch.setenv("SASE_DISABLE_PRETTIER", "1")
    captured: list[list[str]] = []
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=_fake_run_capturing(captured),
        ),
    ):
        format_with_prettier("some prose")

    assert captured, "retired disable env must not skip prettier"


def test_format_with_prettier_failure_returns_text() -> None:
    """A failing prettier still falls back to the original text."""
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["prettier"]),
        ),
    ):
        assert format_with_prettier("untouched", print_width=80) == "untouched"


def test_format_with_prettier_timeout_returns_text() -> None:
    """A timed-out prettier still falls back to the original text."""
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["prettier"], 10.0),
        ),
    ):
        assert format_with_prettier("untouched", print_width=80) == "untouched"


def test_format_markdown_files_uses_one_prettier_process(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("first\\_value\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    captured: list[list[str]] = []

    def run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch("sase.file_references.subprocess.run", side_effect=run),
    ):
        assert format_markdown_files_with_prettier((first, second))

    assert len(captured) == 1
    assert "--write" in captured[0]
    assert str(first) in captured[0]
    assert str(second) in captured[0]
    assert first.read_text(encoding="utf-8") == "first_value\n"


def test_preprocess_prompt_late_uses_named_agent_prompt_formatter() -> None:
    """Launch-time preprocessing routes through the shared prompt policy."""
    from sase.llm_provider.preprocessing import preprocess_prompt_late

    mock_formatter = MagicMock(side_effect=lambda text: text)
    with patch("sase.file_references.format_agent_prompt_markdown", mock_formatter):
        preprocess_prompt_late("just some prompt prose", file_ref_mode="skip")

    mock_formatter.assert_called_once()
