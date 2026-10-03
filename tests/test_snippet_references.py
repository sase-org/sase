"""Tests for process_macro_references function (basic and section macros)."""

from unittest.mock import patch

from sase.macro.models import Macro
from sase.macro.processor import (
    LAUNCH_DEFERRED_MACRO_NAMES,
    process_macro_references,
    prompt_may_reference_macro,
)


def _make_macros(snippets: dict[str, str]) -> dict[str, Macro]:
    """Helper to convert string dict to Macro dict for mocking."""
    return {
        name: Macro(name=name, content=content) for name, content in snippets.items()
    }


# Tests for process_macro_references


def test_prompt_may_reference_macro_false_for_plain_prompt() -> None:
    assert not prompt_may_reference_macro("plain text with no refs")


def test_prompt_may_reference_macro_false_for_vcs_only_tag() -> None:
    assert not prompt_may_reference_macro("#git:master do thing")
    assert not prompt_may_reference_macro("#gh:sase fix issue")


def test_prompt_may_reference_macro_true_for_local_frontmatter_ref() -> None:
    macros = _make_macros({"_ctx": "extra context"})

    assert prompt_may_reference_macro("use #_ctx here", extra_macros=macros)


def test_prompt_may_reference_macro_true_for_macro_candidate_forms() -> None:
    assert prompt_may_reference_macro("#foo")
    assert prompt_may_reference_macro("#foo(arg)")
    assert prompt_may_reference_macro("#foo:arg")
    assert prompt_may_reference_macro("#foo+")
    assert prompt_may_reference_macro("#namespace/foo")
    assert prompt_may_reference_macro("#foo__bar")


def test_process_macro_references_plain_text_skips_catalog_load() -> None:
    with patch("sase.macro.processor.get_all_macros") as get_all:
        result = process_macro_references("plain text with no refs")

    assert result == "plain text with no refs"
    get_all.assert_not_called()


def test_process_macro_references_vcs_only_tag_skips_catalog_load() -> None:
    with (
        patch("sase.config.load_merged_config") as load_config,
        patch("sase.macro.processor.get_all_macros") as get_all,
    ):
        result = process_macro_references("#git:master do thing")

    assert result == "#git:master do thing"
    load_config.assert_not_called()
    get_all.assert_not_called()


def test_process_macro_references_no_snippets_defined() -> None:
    """Test with # but no snippets defined returns unchanged."""
    with patch("sase.macro.processor.get_all_macros", return_value={}):
        result = process_macro_references("Using #foo here")
    assert result == "Using #foo here"


def test_process_macro_references_defers_fork_and_expands_other_refs() -> None:
    snippets = {
        "fork": "SIDE EFFECT",
        "metadata": "%model:gpt-5",
        "wrapper": "#fork:builder wrapped",
    }
    with patch(
        "sase.macro.processor.get_all_macros",
        return_value=_make_macros(snippets),
    ):
        result = process_macro_references(
            "#metadata #fork:builder #wrapper",
            defer_macro_names=LAUNCH_DEFERRED_MACRO_NAMES,
        )

    assert result == "%model:gpt-5 #fork:builder #fork:builder wrapped"


def test_process_macro_references_with_optional_arg_using_default() -> None:
    """Test snippet with optional arg using default value."""
    snippets = {"opt": "Value is {1:DEFAULT}"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#opt()")
    assert result == "Value is DEFAULT"


# Tests for section snippets (content starting with ###)


# Tests for horizontal rule snippets (content starting with ---)


def test_process_macro_heading_content_gets_newline_before_inline_text() -> None:
    """Test that macro ending with heading gets newline when followed by inline text."""
    snippets = {"section": "# New Query"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#section Fix this bug")
    # The heading should be separated from the following text by a blank line
    # (two newlines so that prettier doesn't collapse the separation)
    assert result == "# New Query\n\n Fix this bug"


def test_process_macro_heading_content_no_extra_newline_at_end() -> None:
    """Test that macro ending with heading at end of prompt gets no extra newline."""
    snippets = {"section": "# New Query"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#section")
    # No trailing newline when nothing follows
    assert result == "# New Query"


def test_process_macro_double_underscore_resolves_as_slash() -> None:
    """Test that #foo__bar expands the macro registered as foo/bar."""
    snippets = {"foo/bar": "expanded content"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#foo__bar")
    assert result == "expanded content"


def test_process_macro_double_underscore_multi_level() -> None:
    """Test that #a__b__c expands the macro registered as a/b/c."""
    snippets = {"a/b/c": "deep content"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#a__b__c")
    assert result == "deep content"


def test_process_macro_double_underscore_with_args() -> None:
    """Test that #foo__bar(val) expands with args."""
    snippets = {"foo/bar": "got {1}"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#foo__bar(hello)")
    assert result == "got hello"


def test_process_macro_single_underscore_unchanged() -> None:
    """Test that single underscores are NOT converted to slashes."""
    snippets = {"foo_bar": "single underscore content"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#foo_bar")
    assert result == "single underscore content"


def test_process_macro_heading_content_no_extra_newline_before_newline() -> None:
    """Test that macro ending with heading before a newline gets no extra newline."""
    snippets = {"section": "# New Query"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#section\nFix this bug")
    # No extra newline added since the next char is already a newline
    assert result == "# New Query\nFix this bug"
