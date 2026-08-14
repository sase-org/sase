"""Frozen Patch persistence files for saved queries, history, and selections."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace import query_history, query_selection, saved_queries

_GOLDENS = Path(__file__).resolve().parent / "goldens" / "persistence"


def test_saved_queries_golden_loads_as_current_slot_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        saved_queries, "_SAVED_QUERIES_FILE", _GOLDENS / "saved_queries.json"
    )
    assert saved_queries.load_saved_queries() == {
        "1": "status:Ready",
        "2": '"alpha" AND "beta"',
        "3": "%w",
        "0": "project:myproj",
    }


def test_query_history_golden_loads_as_prev_next_stacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_history, "_QUERY_HISTORY_FILE", _GOLDENS / "query_history.json"
    )
    stacks = query_history.load_query_history()
    assert stacks.prev == ["status:Ready", '"alpha"']
    assert stacks.next == []


def test_query_selections_golden_loads_as_query_to_patch_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_selection, "_QUERY_SELECTION_FILE", _GOLDENS / "query_selections.json"
    )
    assert query_selection.load_query_selections() == {
        "status:Ready": "gamma",
        '"alpha"': "alpha",
    }
