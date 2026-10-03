"""Tests for the parameterized prose wrap width of format_with_prettier."""

import shutil
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


_LITERAL_CASES = [
    "topic__cdx.md \u2026 topic__cld.md\n",
    "/x/gh_sase-org__sase/a__cdx.md\n",
    "__init__.py\n",
    "self.__dict__\n",
    "a___b and c___d\n",
    "src/*.py and tests/*.py\n",
    "x * y * z\n",
    "Snake_case_name and _leading and trailing_\n",
    "5 * 6\n",
    "{%- set _ = ns.layout_lines.append(...) -%}\n",
]


def _rewriting_prettier_run(cmd: list[str], **kwargs: Any) -> Any:
    """Simulate prettier's emphasis rewrites and underscore escapes."""
    text = kwargs["input"]
    text = text.replace("__", "**")
    text = text.replace("*", "_")
    while r"\_" in text:
        text = text.replace(r"\_", "_")
    # Simulate prettier escaping a surviving star.
    text = text.replace("*", r"\*")
    return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")


@pytest.mark.parametrize("text", _LITERAL_CASES)
def test_agent_prompt_formatter_preserves_literals_against_rewriting_prettier(
    text: str,
) -> None:
    """A hostile prettier cannot rewrite protected `_` / `*` literals."""
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=_rewriting_prettier_run,
        ),
    ):
        assert format_agent_prompt_markdown(text) == text


def test_agent_prompt_formatter_missing_prettier_returns_input() -> None:
    """Missing prettier falls back to the original prompt text."""
    with patch("sase.file_references.shutil.which", return_value=None):
        assert format_agent_prompt_markdown("a_b * c\n") == "a_b * c\n"


def test_agent_prompt_formatter_failure_returns_input() -> None:
    """A failing prettier falls back to the original prompt text."""
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["prettier"]),
        ),
    ):
        assert format_agent_prompt_markdown("a_b * c\n") == "a_b * c\n"


def test_agent_prompt_formatter_timeout_returns_input() -> None:
    """A timed-out prettier falls back to the original prompt text."""
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["prettier"], 10.0),
        ),
    ):
        assert format_agent_prompt_markdown("a_b * c\n") == "a_b * c\n"


def test_agent_prompt_formatter_preserves_authored_underscore() -> None:
    """An authored `_` survives because prettier never sees it protected."""
    with (
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch(
            "sase.file_references.subprocess.run",
            side_effect=_rewriting_prettier_run,
        ),
    ):
        assert format_agent_prompt_markdown("foo_bar\n") == "foo_bar\n"


_prettier_required = pytest.mark.skipif(
    shutil.which("prettier") is None, reason="prettier is unavailable"
)


@_prettier_required
@pytest.mark.parametrize("text", _LITERAL_CASES)
def test_agent_prompt_formatter_preserves_table_literals_with_prettier(
    text: str,
) -> None:
    """Every table row survives the real agent-prompt formatter."""
    assert format_agent_prompt_markdown(text) == text


@_prettier_required
def test_preprocess_prompt_late_preserves_table_literals() -> None:
    """Launch-time preprocessing preserves every non-Jinja table literal."""
    from sase.llm_provider.preprocessing import preprocess_prompt_late
    from sase.macro import is_jinja2_template

    for text in _LITERAL_CASES:
        # The table's Jinja row is invalid Jinja (`...` is not valid
        # syntax) and `render_toplevel_jinja2` exits by design, so it is
        # covered through `format_agent_prompt_markdown` above only.
        if is_jinja2_template(text):
            continue
        assert preprocess_prompt_late(text, file_ref_mode="skip") == text
    bare_handoff = "- wait_name=research.m.cdx label=research:202610/t/t__cdx.md\n"
    assert preprocess_prompt_late(bare_handoff, file_ref_mode="skip") == bare_handoff


@_prettier_required
def test_agent_prompt_formatter_still_applies_block_formatting() -> None:
    """List markers still normalize and long prose still wraps."""
    assert format_agent_prompt_markdown("+ item\n") == "- item\n"
    assert format_agent_prompt_markdown("* item\n") == "- item\n"
    width = markdown_print_width()
    paragraph = ("word " * 50).strip() + "\n"
    formatted = format_agent_prompt_markdown(paragraph)
    assert formatted != paragraph
    assert all(len(line) <= width for line in formatted.splitlines())


@_prettier_required
def test_agent_prompt_formatter_wrap_parity_for_intraword_words() -> None:
    """Intraword-only prose wraps exactly like raw prettier."""
    paragraph = " ".join(["snake_case_name", "other_word", "x_y"] * 10) + "\n"
    raw = format_with_prettier(paragraph)
    assert "snake_case_name" in raw
    assert "other_word" in raw
    assert raw == format_agent_prompt_markdown(paragraph)


@_prettier_required
def test_agent_prompt_formatter_standalone_star_never_starts_line() -> None:
    """A `*` at a wrap boundary stays glued instead of becoming a list."""
    base = ("ab " * 50)[:88]
    text = base + " * tail " + "tail " * 30 + "\n"
    formatted = format_agent_prompt_markdown(text)
    assert all(not line.lstrip().startswith("*") for line in formatted.splitlines())


@_prettier_required
def test_agent_prompt_formatter_joins_lines_with_space() -> None:
    """Soft-wrapped literal lines rejoin with a preserved space."""
    assert (
        format_agent_prompt_markdown("ends foo_bar\nbaz__qux\n")
        == "ends foo_bar baz__qux\n"
    )
