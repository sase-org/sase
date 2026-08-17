"""Tests for the completion-candidates wire format."""

from __future__ import annotations

from sase.completion.candidates.protocol import (
    Candidate,
    candidate_from_line,
    candidate_to_line,
    filter_candidates,
    render_candidates,
)


def test_candidate_to_line_without_description_is_bare_value() -> None:
    assert candidate_to_line(Candidate("sase-1")) == "sase-1"


def test_candidate_to_line_with_description_is_tab_separated() -> None:
    assert candidate_to_line(Candidate("sase-1", "Fix the thing")) == (
        "sase-1\tFix the thing"
    )


def test_candidate_to_line_sanitizes_embedded_tabs_and_newlines() -> None:
    candidate = Candidate("va\tlue", "de\nscri\rption")

    line = candidate_to_line(candidate)

    assert "\t" not in line.split("\t", 1)[0]
    assert line == "va lue\tde scri ption"


def test_candidate_from_line_roundtrips_with_description() -> None:
    candidate = Candidate("sase-1", "Fix the thing")

    assert candidate_from_line(candidate_to_line(candidate)) == candidate


def test_candidate_from_line_without_tab_has_empty_description() -> None:
    assert candidate_from_line("sase-1") == Candidate("sase-1", "")


def test_render_candidates_joins_with_newlines() -> None:
    candidates = [Candidate("a", "A"), Candidate("b")]

    assert render_candidates(candidates) == "a\tA\nb"


def test_render_candidates_empty_is_empty_string() -> None:
    assert render_candidates([]) == ""


def test_filter_candidates_applies_prefix() -> None:
    candidates = [Candidate("sase-1"), Candidate("sase-2"), Candidate("other")]

    assert filter_candidates(candidates, "sase-", 200) == [
        Candidate("sase-1"),
        Candidate("sase-2"),
    ]


def test_filter_candidates_empty_prefix_matches_everything() -> None:
    candidates = [Candidate("a"), Candidate("b")]

    assert filter_candidates(candidates, "", 200) == candidates


def test_filter_candidates_applies_limit_after_prefix_filter() -> None:
    candidates = [Candidate(f"sase-{i}") for i in range(10)]

    result = filter_candidates(candidates, "sase-", 3)

    assert result == candidates[:3]


def test_filter_candidates_negative_limit_returns_all_matches() -> None:
    candidates = [Candidate("a"), Candidate("b")]

    assert filter_candidates(candidates, "", -1) == candidates
