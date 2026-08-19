"""Tests for tmux Agent window naming and renumber planning."""

from __future__ import annotations

from sase.tmux_agent.window import next_window_name, renumber_plan


def test_next_window_name_no_matches_returns_base() -> None:
    assert next_window_name("ai", ["shell", "logs"]) == "ai"


def test_next_window_name_empty_existing_returns_base() -> None:
    assert next_window_name("ai", []) == "ai"


def test_next_window_name_base_taken_returns_ai2() -> None:
    assert next_window_name("ai", ["ai"]) == "ai2"


def test_next_window_name_fills_first_gap() -> None:
    assert next_window_name("ai", ["ai", "ai2", "ai4"]) == "ai3"


def test_next_window_name_appends_after_dense_run() -> None:
    assert next_window_name("ai", ["ai", "ai2", "ai3"]) == "ai4"


def test_next_window_name_ignores_unrelated_windows() -> None:
    assert next_window_name("ai", ["ai", "aiden", "shell"]) == "ai2"


def test_next_window_name_matches_suffix_only_windows() -> None:
    assert next_window_name("ai", ["ai3", "ai5"]) == "ai2"


def test_renumber_plan_noop_when_already_correct() -> None:
    windows = [(1, "ai"), (2, "ai2"), (3, "ai3")]
    assert renumber_plan("ai", windows) == ()


def test_renumber_plan_closes_gaps() -> None:
    windows = [(1, "ai"), (2, "ai3"), (3, "ai5")]
    assert renumber_plan("ai", windows) == ((2, "ai2"), (3, "ai3"))


def test_renumber_plan_ignores_unrelated_windows() -> None:
    windows = [(1, "ai"), (2, "shell"), (3, "ai3")]
    assert renumber_plan("ai", windows) == ((3, "ai2"),)


def test_renumber_plan_sorts_by_window_index_regardless_of_input_order() -> None:
    windows = [(5, "ai3"), (1, "ai"), (3, "ai2")]
    assert renumber_plan("ai", windows) == ()


def test_renumber_plan_reversed_indices_still_renumber_in_index_order() -> None:
    windows = [(9, "ai"), (4, "ai2"), (1, "ai3")]
    # Sorted by index ascending: (1, "ai3"), (4, "ai2"), (9, "ai") -> ai, ai2, ai3
    assert renumber_plan("ai", windows) == ((1, "ai"), (9, "ai3"))


def test_renumber_plan_empty_windows() -> None:
    assert renumber_plan("ai", []) == ()


def test_renumber_plan_no_matching_windows() -> None:
    windows = [(1, "shell"), (2, "logs")]
    assert renumber_plan("ai", windows) == ()
