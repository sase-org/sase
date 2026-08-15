"""Frozen legacy persistence files migrate cleanly onto the Patches pane."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from sase.ace import query_history, query_selection, saved_queries

_GOLDENS = Path(__file__).resolve().parent / "goldens" / "persistence"


def _copy_golden(name: str, tmp_path: Path) -> Path:
    """Copy a frozen legacy fixture into *tmp_path* before pointing a store at it.

    Loading a legacy file migrates it in place (write-then-read validated),
    so the store must never be pointed directly at the checked-in golden --
    that would mutate the frozen fixture as a side effect of running tests.
    """
    dest = tmp_path / name
    shutil.copy(_GOLDENS / name, dest)
    return dest


def test_saved_queries_golden_migrates_onto_patches_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        saved_queries,
        "_SAVED_QUERIES_FILE",
        _copy_golden("saved_queries.json", tmp_path),
    )
    result = saved_queries.load_saved_queries("patches")
    assert {slot: record.canonical for slot, record in result.items()} == {
        "1": "status:Ready",
        "2": '"alpha" AND "beta"',
        "3": "%w",
        "0": "project:myproj",
    }
    assert all(record.source == record.canonical for record in result.values())
    # The legacy file was implicitly Patches-only; other panes stay empty.
    assert saved_queries.load_saved_queries("stitches") == {}


def test_query_history_golden_migrates_onto_patches_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        query_history,
        "_QUERY_HISTORY_FILE",
        _copy_golden("query_history.json", tmp_path),
    )
    stacks = query_history.load_query_history("patches")
    assert [r.canonical for r in stacks.prev] == ["status:Ready", '"alpha"']
    assert stacks.next == []
    assert query_history.load_query_history(
        "stitches"
    ) == query_history.QueryHistoryStacks(prev=[], next=[])


def test_query_selections_golden_migrates_onto_patches_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        query_selection,
        "_QUERY_SELECTION_FILE",
        _copy_golden("query_selections.json", tmp_path),
    )
    assert query_selection.load_query_selections("patches") == {
        "status:Ready": "gamma",
        '"alpha"': "alpha",
    }
    assert query_selection.load_query_selections("stitches") == {}
