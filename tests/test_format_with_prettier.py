"""Tests for the parameterized prose wrap width of format_with_prettier."""

import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.file_references import (
    AGENT_PROMPT_WRAP_WIDTH,
    DEFAULT_MARKDOWN_WRAP_WIDTH,
    format_with_prettier,
)


@pytest.fixture(autouse=True)
def _prettier_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_DISABLE_PRETTIER", raising=False)


def _fake_run_capturing(captured: list[list[str]]) -> Any:
    """Build a subprocess.run stand-in that records argv and echoes input."""

    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=kwargs["input"], stderr="")

    return _run


def test_format_with_prettier_default_uses_120() -> None:
    """The default call wraps prose at DEFAULT_MARKDOWN_WRAP_WIDTH (120)."""
    assert DEFAULT_MARKDOWN_WRAP_WIDTH == 120

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
    assert "--print-width=120" in captured[0]
    assert "--print-width=80" not in captured[0]


def test_format_with_prettier_override_uses_80() -> None:
    """An explicit print_width override flows through to prettier's argv."""
    assert AGENT_PROMPT_WRAP_WIDTH == 80

    captured: list[list[str]] = []
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=_fake_run_capturing(captured),
        ),
    ):
        format_with_prettier("some prose", print_width=AGENT_PROMPT_WRAP_WIDTH)

    assert captured, "prettier should have been invoked"
    assert "--print-width=80" in captured[0]
    assert "--print-width=120" not in captured[0]


def test_format_with_prettier_missing_prettier_returns_text() -> None:
    """Fallback behavior is unchanged when prettier is unavailable."""
    with patch("sase.file_references.shutil.which", return_value=None):
        assert format_with_prettier("untouched", print_width=80) == "untouched"


def test_format_with_prettier_disabled_returns_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment switch bypasses prettier even when it is installed."""
    monkeypatch.setenv("SASE_DISABLE_PRETTIER", "1")
    with patch(
        "sase.file_references.shutil.which", return_value="/usr/bin/prettier"
    ) as mock_which:
        assert format_with_prettier("untouched", print_width=80) == "untouched"

    mock_which.assert_not_called()


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


def test_preprocess_prompt_late_passes_agent_prompt_width() -> None:
    """Launch-time preprocessing wraps agent prompts at AGENT_PROMPT_WRAP_WIDTH."""
    from sase.llm_provider.preprocessing import preprocess_prompt_late

    mock_prettier = MagicMock(side_effect=lambda text, **_kw: text)
    with patch("sase.file_references.format_with_prettier", mock_prettier):
        preprocess_prompt_late("just some prompt prose", file_ref_mode="skip")

    assert mock_prettier.called
    assert mock_prettier.call_args.kwargs.get("print_width") == AGENT_PROMPT_WRAP_WIDTH
    assert AGENT_PROMPT_WRAP_WIDTH == 80
