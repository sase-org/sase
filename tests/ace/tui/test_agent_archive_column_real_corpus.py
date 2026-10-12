"""Archive list against the real Rust-backed corpus (no model corpus in the loop).

Guards the contract the list depends on: the host ``in:`` scope is stripped
before core calls, summaries count presentation roots, ``rows`` flattens
expanded containers, and the corpus timezone decides the day banners.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui.models.agent_archive_view import INTENT_ACTIVATE, INTENT_DOWN
from sase.ace.tui.actions.agents._archive_controller import archive_corpus_snapshot
from sase.ace.tui.actions.agents._archive_view import (
    open_agents_archive_view,
    route_archive_key,
)
from sase.ace.tui.models.agent_archive_list import archive_row_key
from sase.core.agent_archive_facade import compile_agent_archive_corpus
from sase.feature_flags import override_flags
from tests._agent_archive_index_fixtures import insert_archive_rows
from tests.ace.tui._agent_archive_column_helpers import ColumnHarness


def _real_corpus(tmp_path: Path, rows: list[dict[str, Any]], zone: str = "UTC"):
    insert_archive_rows(tmp_path, rows)
    return compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "ok"},
        timezone=zone,
        link_facets={},
    )


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "run_id": "r1",
            "name": "261010.alpha",
            "stop_time": "2026-10-10T15:05:00Z",
            "clan": "swarm",
            "clan_generation": "1",
        },
        {
            "run_id": "r2",
            "name": "261010.beta",
            "stop_time": "2026-10-10T14:05:00Z",
            "clan": "swarm",
            "clan_generation": "1",
        },
        {
            "run_id": "r3",
            "name": "261010.gamma",
            "stop_time": "2026-10-10T13:30:00Z",
            "status": "FAILED",
        },
        {
            "run_id": "r4",
            "name": "261009.delta",
            "stop_time": None,
            "start_time": "2026-10-09T12:00:00Z",
            "status": "RUNNING",
        },
    ]


async def test_real_corpus_lists_roots_containers_and_expanded_members(
    tmp_path: Path,
) -> None:
    corpus = _real_corpus(tmp_path, _rows())
    harness = ColumnHarness([], corpus=corpus)
    harness.note_inbox_applied()
    open_agents_archive_view(harness.owner)
    await harness.settle()

    snapshot = archive_corpus_snapshot(harness.owner)
    assert snapshot.summary is not None, "in:archive must reach the corpus stripped"
    assert snapshot.summary["total"] == 3  # roots: clan, gamma, delta
    assert snapshot.timezone == "UTC"
    labels = harness.widget.last_labels()
    assert labels == [
        "v Today (2)",
        "container:clan:swarm:1",
        "bbugyi200.athena@r3",
        "v Yesterday (1)",
        "bbugyi200.athena@r4",
    ]

    harness.archive.selected_key = "container:clan:swarm:1"
    route_archive_key(harness.owner, "expand")
    await harness.settle()
    assert harness.widget.last_labels()[:5] == [
        "v Today (2)",
        "container:clan:swarm:1",
        "bbugyi200.athena@r1",
        "bbugyi200.athena@r2",
        "bbugyi200.athena@r3",
    ]
    container = harness.widget.last_items[1]
    assert container.count == 2 and container.expanded
    # Keys round-trip through the stable identity helper.
    keys = [archive_row_key(item.row) for item in harness.widget.last_items if item.row]
    assert keys == [
        "container:clan:swarm:1",
        "bbugyi200.athena@r1",
        "bbugyi200.athena@r2",
        "bbugyi200.athena@r3",
        "bbugyi200.athena@r4",
    ]
    assert harness.widget.last_items[-1].row["outcome"] == "interrupted"
    assert harness.widget.last_items[-1].row["time_basis"] == "started"


async def test_list_order_matches_the_corpus_row_order(tmp_path: Path) -> None:
    corpus = _real_corpus(tmp_path, _rows())
    harness = ColumnHarness([], corpus=corpus)
    harness.note_inbox_applied()
    open_agents_archive_view(harness.owner)
    await harness.settle()

    summary = corpus.summary("", group_by="day")
    expected: list[str] = []
    for group in summary["groups"]:
        window = corpus.rows(
            "", group_by="day", group_key=group["key"], offset=0, limit=100
        )
        expected.extend(archive_row_key(row) or "" for row in window["rows"])
    listed = [item.key for item in harness.widget.last_items if item.row]
    assert listed == expected


async def test_corpus_timezone_decides_the_day_banner(tmp_path: Path) -> None:
    rows = [
        {
            "run_id": "late",
            "name": "261011.late",
            "stop_time": "2026-10-11T02:30:00Z",  # still Oct 10 in New York
        },
        {
            "run_id": "early",
            "name": "261010.early",
            "stop_time": "2026-10-10T15:00:00Z",
        },
    ]
    corpus = _real_corpus(tmp_path, rows, zone="America/New_York")
    harness = ColumnHarness([], corpus=corpus)
    harness.note_inbox_applied()
    open_agents_archive_view(harness.owner)
    await harness.settle()

    labels = harness.widget.last_labels()
    assert labels == [
        "v Today (2)",
        "bbugyi200.athena@late",
        "bbugyi200.athena@early",
    ]
    assert str(harness.widget.paints[-1]["tz"]) == "America/New_York"


async def test_real_corpus_pages_and_cursor_move_without_inbox_effects(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "run_id": f"p{i:03d}",
            "name": f"261010.p{i:03d}",
            "stop_time": f"2026-10-10T{(i // 20) + 1:02d}:{i % 60:02d}:00Z",
        }
        for i in range(130)
    ]
    corpus = _real_corpus(tmp_path, rows)
    harness = ColumnHarness([], corpus=corpus)
    harness.note_inbox_applied()
    open_agents_archive_view(harness.owner)
    await harness.settle()

    labels = harness.widget.last_labels()
    assert sum(1 for label in labels if label.startswith("bbugyi200")) == 100
    assert labels[-1] == "tail 30"
    harness.archive.selected_key = "tail:day:2026-10-10"
    route_archive_key(harness.owner, INTENT_ACTIVATE)
    await harness.settle()
    labels = harness.widget.last_labels()
    assert sum(1 for label in labels if label.startswith("bbugyi200")) == 130
    route_archive_key(harness.owner, INTENT_DOWN)
    assert harness.owner._agents == []


async def test_scoped_query_filters_through_the_real_corpus(tmp_path: Path) -> None:
    corpus = _real_corpus(tmp_path, _rows())
    harness = ColumnHarness([], corpus=corpus)
    harness.note_inbox_applied()
    harness.archive.committed_query = "in:archive outcome:failed"
    open_agents_archive_view(harness.owner)
    await harness.settle()

    assert harness.widget.last_labels() == [
        "v Today (1)",
        "bbugyi200.athena@r3",
    ]


async def test_rejected_scope_paints_an_honest_unavailable_note(tmp_path: Path) -> None:
    corpus = _real_corpus(tmp_path, _rows())
    harness = ColumnHarness([], corpus=corpus)
    harness.note_inbox_applied()
    harness.archive.committed_query = "in:nowhere"
    open_agents_archive_view(harness.owner)
    await harness.settle()

    assert harness.widget.last_labels() == ["~ Archive results unavailable"]
    assert archive_corpus_snapshot(harness.owner).summary is None
