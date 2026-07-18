"""Tests for prompt directive argument token extraction."""

from __future__ import annotations

from sase.ace.tui.widgets.directive_completion import (
    extract_directive_arg_token_around_cursor,
)


def test_directive_arg_extraction_detects_empty_partial_and_alias() -> None:
    assert extract_directive_arg_token_around_cursor("%effort:", len("%effort:")) == (
        8,
        8,
        "effort",
        "",
    )
    assert extract_directive_arg_token_around_cursor("%a:", len("%a:")) == (
        3,
        3,
        "auto",
        "",
    )
    # %e is the %effort alias, so %e: classifies as the canonical effort context.
    assert extract_directive_arg_token_around_cursor("%e:xh", len("%e:xh")) == (
        3,
        len("%e:xh"),
        "effort",
        "xh",
    )


def test_directive_arg_extraction_returns_partial_span() -> None:
    line = "run %effort:hi now"
    col = line.index(" now")
    assert extract_directive_arg_token_around_cursor(line, col) == (
        line.index(":") + 1,
        col,
        "effort",
        "hi",
    )


def test_directive_arg_extraction_accepts_model_alias_and_special_chars() -> None:
    assert extract_directive_arg_token_around_cursor(
        "%m:gpt-5.6-sol", len("%m:gpt-5.6-sol")
    ) == (
        3,
        len("%m:gpt-5.6-sol"),
        "model",
        "gpt-5.6-sol",
    )
    line = "%model:anthropic/claude-sonnet-4-5"
    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        len("%model:"),
        len(line),
        "model",
        "anthropic/claude-sonnet-4-5",
    )


def test_wait_arg_extraction_uses_active_comma_fragment_and_alias() -> None:
    line = "%w:planner, family.cod"
    col = len(line)
    assert extract_directive_arg_token_around_cursor(line, col) == (
        line.index("family"),
        col,
        "wait",
        "family.cod",
    )


def test_wait_arg_extraction_accepts_tribe_reference_prefix() -> None:
    line = "%w:planner, @ep"
    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        line.index("@ep"),
        len(line),
        "wait",
        "@ep",
    )


def test_wait_arg_extraction_supports_paren_form_and_time_fragment() -> None:
    line = "%wait(planner, co, time=5m)"
    col = line.index(", time")
    assert extract_directive_arg_token_around_cursor(line, col) == (
        line.index("co"),
        col,
        "wait",
        "co",
    )

    time_col = line.index(")")
    assert extract_directive_arg_token_around_cursor(line, time_col) == (
        line.index("time="),
        time_col,
        "wait",
        "time=5m",
    )


def test_wait_arg_extraction_rejects_prose_comma_after_directive() -> None:
    # A line that begins with a valid wait directive then continues with normal
    # prose must not treat a later prose comma as a new wait argument fragment.
    line = "%w:sase-59 Can you help me get rid of the ,"
    assert extract_directive_arg_token_around_cursor(line, len(line)) is None

    paren_line = "%wait(sase-59 fix the bug ,"
    assert (
        extract_directive_arg_token_around_cursor(paren_line, len(paren_line)) is None
    )


def test_wait_arg_extraction_keeps_valid_comma_fragments() -> None:
    # Valid comma-separated wait fragments must continue to extract, including a
    # trailing comma that begins a fresh (empty) agent fragment.
    for line, expected_partial in (
        ("%wait:planner, co", "co"),
        ("%wait:planner,", ""),
        ("%wait(planner, co, time=5m", "time=5m"),
    ):
        result = extract_directive_arg_token_around_cursor(line, len(line))
        assert result is not None
        assert result[2] == "wait"
        assert result[3] == expected_partial


def test_directive_arg_extraction_redirects_model_at_suffix_to_effort() -> None:
    assert extract_directive_arg_token_around_cursor(
        "%model:opus@",
        len("%model:opus@"),
    ) == (
        len("%model:opus@"),
        len("%model:opus@"),
        "effort",
        "",
    )
    assert extract_directive_arg_token_around_cursor(
        "%model:opus@xh",
        len("%model:opus@xh"),
    ) == (
        len("%model:opus@"),
        len("%model:opus@xh"),
        "effort",
        "xh",
    )


def test_directive_arg_extraction_rejects_non_argument_contexts() -> None:
    assert extract_directive_arg_token_around_cursor("%effort", len("%effort")) is None
    assert extract_directive_arg_token_around_cursor("%effort:", 4) is None
    assert (
        extract_directive_arg_token_around_cursor(
            "word%effort:",
            len("word%effort:"),
        )
        is None
    )
    assert (
        extract_directive_arg_token_around_cursor("%unknown:", len("%unknown:")) is None
    )
    assert (
        extract_directive_arg_token_around_cursor(
            "%effort:high ",
            len("%effort:high "),
        )
        is None
    )
    assert (
        extract_directive_arg_token_around_cursor(
            "%effort:hi.now",
            len("%effort:hi.now"),
        )
        is None
    )
