"""Tests for sase.completion.shorten."""

from __future__ import annotations

import argparse

from sase.completion.shorten import (
    get_completion_summary,
    set_completion_summary,
    short_summary,
)


def test_takes_first_sentence_and_strips_trailing_period() -> None:
    text = "Show issue details. Extra detail that gets dropped."
    assert short_summary(text) == "Show issue details"


def test_collapses_internal_whitespace_and_newlines() -> None:
    text = "Do   the\nthing.\nMore prose that is dropped."
    assert short_summary(text) == "Do the thing"


def test_strips_backticks() -> None:
    assert (
        short_summary("Route through `sase_core_rs`.") == "Route through sase_core_rs"
    )


def test_respects_common_abbreviations_when_splitting_sentences() -> None:
    text = "Route via sase_core_rs, e.g. a Rust binding. Second sentence is dropped."
    assert short_summary(text) == "Route via sase_core_rs, e.g. a Rust binding"


def test_exact_limit_boundary_is_not_truncated() -> None:
    sentence = "x" * 60
    result = short_summary(f"{sentence}.")
    assert result == sentence
    assert len(result) == 60


def test_one_over_limit_is_truncated_with_ellipsis() -> None:
    sentence = "x" * 61
    result = short_summary(f"{sentence}.")
    assert len(result) <= 60
    assert result.endswith("…")


def test_truncates_at_word_boundary_not_mid_word() -> None:
    words = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "kilo",
        "lima",
    ]
    help_text = " ".join(words * 3)
    assert len(help_text) > 60

    result = short_summary(help_text)
    assert result.endswith("…")
    body = result[:-1]
    assert len(result) <= 60
    assert help_text.startswith(body)
    assert help_text[len(body)] == " "


def test_271_char_help_string_is_shortened_below_limit() -> None:
    help_text = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet " * 5)[
        :271
    ]
    assert len(help_text) == 271

    result = short_summary(help_text)
    assert len(result) <= 60
    assert result.endswith("…")


def test_summary_override_round_trips_on_action() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_argument("--foo")
    assert get_completion_summary(action) is None

    set_completion_summary(action, "Explicit short text")
    assert get_completion_summary(action) == "Explicit short text"
