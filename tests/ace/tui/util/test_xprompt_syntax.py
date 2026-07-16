"""Tests for Markdown + xprompt prompt syntax highlighting."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.util.lazy_syntax import MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
from sase.ace.tui.util.xprompt_syntax import (
    XPROMPT_TOKEN_STYLES,
    highlight_prompt_text,
)


def _styles_at(text: Text, needle: str, *, offset: int = 0) -> set[str]:
    position = text.plain.index(needle) + offset
    return {
        str(span.style)
        for span in text.spans
        if span.start <= position < span.end and span.style is not None
    }


def test_highlights_reference_forms_and_arguments() -> None:
    source = (
        "#foo #!bar #ns/name #args(a, k=v) #colon:value "
        "#quoted:`two words` #plus+ #ask!! #skip??"
    )
    highlighted = highlight_prompt_text(source)

    for token in (
        "#foo",
        "#!bar",
        "#ns/name",
        "#args",
        "#colon",
        "#quoted",
        "#plus",
        "#ask!!",
        "#skip??",
    ):
        assert XPROMPT_TOKEN_STYLES["invocation"] in _styles_at(highlighted, token)
    for token in ("(a, k=v)", ":value", ":`two words`", "+"):
        assert XPROMPT_TOKEN_STYLES["invocation_arg"] in _styles_at(highlighted, token)


def test_highlights_known_directives_aliases_and_arguments_only() -> None:
    highlighted = highlight_prompt_text(
        "%wait:x %w %model(opus) %m:sonnet %auto %notadirective"
    )

    for token in ("%wait", "%w", "%model", "%m", "%auto"):
        assert XPROMPT_TOKEN_STYLES["directive"] in _styles_at(highlighted, token)
    for token in (":x", "(opus)", ":sonnet"):
        assert XPROMPT_TOKEN_STYLES["directive_arg"] in _styles_at(highlighted, token)
    assert XPROMPT_TOKEN_STYLES["directive"] not in _styles_at(
        highlighted, "%notadirective"
    )


def test_highlights_only_known_skills_when_catalog_is_supplied() -> None:
    source = "Use /sase_plan but leave /unknown literal"

    without_catalog = highlight_prompt_text(source)
    with_catalog = highlight_prompt_text(
        source,
        known_skills=frozenset({"sase_plan"}),
    )

    assert XPROMPT_TOKEN_STYLES["skill"] not in _styles_at(
        without_catalog,
        "/sase_plan",
    )
    assert XPROMPT_TOKEN_STYLES["skill"] in _styles_at(
        with_catalog,
        "/sase_plan",
    )
    assert XPROMPT_TOKEN_STYLES["skill"] not in _styles_at(
        with_catalog,
        "/unknown",
    )


def test_highlights_alt_structure_and_segment_separator() -> None:
    highlighted = highlight_prompt_text("%{one | nested(x | y) | three}\n---\n")

    assert XPROMPT_TOKEN_STYLES["alt_delimiter"] in _styles_at(highlighted, "%{")
    assert XPROMPT_TOKEN_STYLES["alt_delimiter"] in _styles_at(
        highlighted, " | ", offset=1
    )
    assert XPROMPT_TOKEN_STYLES["alt_delimiter"] not in _styles_at(
        highlighted, "x | y", offset=2
    )
    assert XPROMPT_TOKEN_STYLES["alt_delimiter"] in _styles_at(
        highlighted, "three}", offset=5
    )
    assert XPROMPT_TOKEN_STYLES["separator"] in _styles_at(highlighted, "---")


def test_highlights_all_alt_forms_branch_names_and_errors() -> None:
    source = "%alt(fast=a, slow=b) %(left, right) %{one=x | two=y} %{oops"
    highlighted = highlight_prompt_text(source)

    for token in ("%alt(", "%(", "%{"):
        assert XPROMPT_TOKEN_STYLES["alt_delimiter"] in _styles_at(highlighted, token)
    for token in ("fast", "slow", "one", "two"):
        assert XPROMPT_TOKEN_STYLES["branch_name"] in _styles_at(highlighted, token)
    assert XPROMPT_TOKEN_STYLES["error"] in _styles_at(highlighted, "%{oops")


def test_protected_regions_keep_xprompt_tokens_literal() -> None:
    source = (
        "```text\n#fenced %wait:fenced\n---\n```\n"
        "%xprompts_enabled:false\n#disabled %m:disabled\n---\n"
        "%xprompts_enabled:true\n"
        "#active %wait:active\n---"
    )
    highlighted = highlight_prompt_text(source)

    for token in ("#fenced", "%wait:fenced", "#disabled", "%m:disabled"):
        assert XPROMPT_TOKEN_STYLES["invocation"] not in _styles_at(highlighted, token)
        assert XPROMPT_TOKEN_STYLES["directive"] not in _styles_at(highlighted, token)
    assert XPROMPT_TOKEN_STYLES["invocation"] in _styles_at(highlighted, "#active")
    assert XPROMPT_TOKEN_STYLES["directive"] in _styles_at(highlighted, "%wait:active")
    assert (
        sum(
            1
            for span in highlighted.spans
            if str(span.style) == XPROMPT_TOKEN_STYLES["separator"]
        )
        == 1
    )


def test_markdown_heading_and_midword_tokens_are_not_xprompts() -> None:
    highlighted = highlight_prompt_text("# Heading\nword#foo word%wait")

    assert XPROMPT_TOKEN_STYLES["invocation"] not in _styles_at(
        highlighted, "# Heading"
    )
    assert XPROMPT_TOKEN_STYLES["invocation"] not in _styles_at(
        highlighted, "word#foo", offset=4
    )
    assert XPROMPT_TOKEN_STYLES["directive"] not in _styles_at(
        highlighted, "word%wait", offset=4
    )


def test_oversized_prompt_falls_back_to_plain_text() -> None:
    source = "#foo " + "x" * MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
    highlighted = highlight_prompt_text(source)

    assert highlighted.plain == source
    assert highlighted.spans == []


def test_highlighting_exception_falls_back_to_plain_text(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("sase.ace.tui.util.xprompt_syntax.Syntax.highlight", _raise)
    highlighted = highlight_prompt_text("#foo")

    assert highlighted.plain == "#foo"
    assert highlighted.spans == []
