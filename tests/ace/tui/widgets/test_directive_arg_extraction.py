"""Tests for prompt directive argument token extraction."""

from __future__ import annotations

from sase.ace.tui.widgets.directive_completion import (
    classify_directive_completion,
    extract_directive_arg_token_around_cursor,
    selected_wait_values_around_cursor,
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


def test_clan_arg_extraction_recognizes_summary_keyword_fragment() -> None:
    line = "%clan(research, su"

    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        line.index("su"),
        len(line),
        "clan_keyword",
        "su",
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
        line.index("5m"),
        time_col,
        "wait",
        "5m",
    )


def test_directive_arg_completion_ranges_stop_at_unterminated_body_prose() -> None:
    _assert_clause_range("%wait:co and then do the thing", 8, 6, 8, "co")
    _assert_clause_range("%wait: do the thing", len("%wait:"), 6, 6, "")
    _assert_clause_range("%wait:planner, co", len("%wait:planner, co"), 15, 17, "co")
    _assert_clause_range("%wait:planner,", len("%wait:planner,"), 14, 14, "")
    _assert_clause_range("%wait(planner, co", len("%wait(planner, co"), 15, 17, "co")

    closed = "%wait(planner, co) and more prose"
    _assert_clause_range(closed, closed.index(")"), 15, 17, "co")

    _assert_clause_range("%id(foo and more prose", len("%id(fo"), 4, 7, "foo")
    _assert_clause_range(
        "%model(son and more prose",
        len("%model(son"),
        7,
        10,
        "son",
    )
    _assert_clause_range("%clan(rev and more prose", len("%clan(rev"), 6, 9, "rev")
    _assert_clause_range(
        "%final(sase and more prose",
        len("%final(sase"),
        7,
        11,
        "sase",
    )
    _assert_clause_range("%wait:`my agent` ", len("%wait:`my"), 6, 16, "`my agent`")

    prose = "%w:sase-59 Can you help me get rid of the ,"
    assert classify_directive_completion(prose, len(prose)) is None


def test_wait_arg_extraction_reports_selected_values_on_both_sides() -> None:
    line = "%wait(planner, co, @builders, time=5m)"
    active_start = line.index("co")

    assert selected_wait_values_around_cursor(line, active_start) == frozenset(
        {"planner", "@builders", "time=5m"}
    )


def test_wait_arg_extraction_tracks_keyword_and_target_values_to_the_right() -> None:
    line = "%wait:, runners=1, Coder"

    assert selected_wait_values_around_cursor(line, len("%wait:")) == frozenset(
        {"runners=1", "Coder"}
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
        ("%wait(planner, co, time=5m", "5m"),
    ):
        result = extract_directive_arg_token_around_cursor(line, len(line))
        assert result is not None
        assert result[2] == "wait"
        assert result[3] == expected_partial


def test_directive_arg_extraction_redirects_model_at_suffix_to_effort() -> None:
    for line, expected_partial in (
        ("%model:opus@", ""),
        ("%model:opus@xh", "xh"),
    ):
        assert extract_directive_arg_token_around_cursor(line, len(line)) == (
            len("%model:opus@"),
            len(line),
            "effort",
            expected_partial,
        )


def test_directive_arg_extraction_keeps_leading_at_model_alias_context() -> None:
    for line, expected_start, expected_partial in (
        ("%m:@", len("%m:"), "@"),
        ("%m:@def", len("%m:"), "@def"),
        ("%model:@medium", len("%model:"), "@medium"),
    ):
        assert extract_directive_arg_token_around_cursor(line, len(line)) == (
            expected_start,
            len(line),
            "model",
            expected_partial,
        )


def test_directive_arg_extraction_redirects_alias_effort_suffix_to_effort() -> None:
    line = "%model:@large@hi"

    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        len("%model:@large@"),
        len(line),
        "effort",
        "hi",
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


def _assert_clause_range(
    line: str,
    col: int,
    start: int,
    end: int,
    replaced_text: str,
) -> None:
    clause = classify_directive_completion(line, col)
    assert clause is not None
    assert (clause.start, clause.end) == (start, end)
    assert line[clause.start : clause.end] == replaced_text
