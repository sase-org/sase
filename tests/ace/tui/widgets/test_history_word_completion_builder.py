"""Pure builder tests for prompt-history word completion results."""

from __future__ import annotations

from sase.ace.tui.widgets.history_word_completion import (
    build_history_word_completion_result,
)


def test_history_builder_filters_casefold_prefix_in_mru_order() -> None:
    result = build_history_word_completion_result(
        "aL",
        2,
        ["ALPINE", "Alpha", "alphabet", "other"],
    )

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == [
        "ALPINE",
        "aLpha",
        "aLphabet",
    ]
    assert [candidate.name for candidate in result.candidates] == [
        "ALPINE",
        "Alpha",
        "alphabet",
    ]
    assert result.shared_extension == "P"


def test_history_builder_collapses_case_variants_by_mru_spelling() -> None:
    result = build_history_word_completion_result(
        "git",
        len("git"),
        ["github", "GitHub", "Github", "gitlab"],
    )

    assert result is not None
    assert [candidate.name for candidate in result.candidates] == ["github", "gitlab"]
    assert [candidate.insertion for candidate in result.candidates] == [
        "github",
        "gitlab",
    ]


def test_history_builder_replaces_only_the_prefix_and_preserves_suffix() -> None:
    text = "pubZZZ"
    result = build_history_word_completion_result(
        text,
        len("pub"),
        ["pub", "publish", "publication"],
    )

    assert result is not None
    assert text[result.replacement_start : result.replacement_end] == "pub"
    assert result.replacement_end == len("pub")
    assert result.has_word_suffix is True
    assert [candidate.insertion for candidate in result.candidates] == [
        "pub",
        "publish",
        "publication",
    ]


def test_history_builder_suppresses_exact_prefix_spelling_without_suffix() -> None:
    result = build_history_word_completion_result(
        "pub",
        len("pub"),
        ["pub", "publish", "publication"],
    )

    assert result is not None
    assert result.has_word_suffix is False
    assert [candidate.insertion for candidate in result.candidates] == [
        "publish",
        "publication",
    ]


def test_history_builder_suppresses_noop_after_case_policy() -> None:
    assert (
        build_history_word_completion_result(
            "readme",
            len("readme"),
            ["readme"],
        )
        is None
    )

    result = build_history_word_completion_result(
        "github",
        len("github"),
        ["GitHub"],
    )

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == ["GitHub"]


def test_history_builder_ignores_suffix_when_filtering() -> None:
    with_suffix = build_history_word_completion_result(
        "pubZZZ", len("pub"), ["publish", "publication"]
    )
    without_suffix = build_history_word_completion_result(
        "pub", len("pub"), ["publish", "publication"]
    )

    assert with_suffix is not None
    assert without_suffix is not None
    assert (
        [candidate.insertion for candidate in with_suffix.candidates]
        == [candidate.insertion for candidate in without_suffix.candidates]
        == ["publish", "publication"]
    )


def test_history_builder_uses_hyphenated_prefix_and_prefix_only_range() -> None:
    text = "bob-maZZZ"
    result = build_history_word_completion_result(
        text,
        len("bob-ma"),
        ["bob-mac-capture"],
    )

    assert result is not None
    assert result.prefix == "bob-ma"
    assert text[result.replacement_start : result.replacement_end] == "bob-ma"
    assert result.replacement_end == len("bob-ma")
    assert result.has_word_suffix is True
    assert [candidate.insertion for candidate in result.candidates] == [
        "bob-mac-capture"
    ]
