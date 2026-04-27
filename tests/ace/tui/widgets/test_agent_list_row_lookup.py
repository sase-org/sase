"""Tests for the O(1) row-lookup maps on ``AgentList`` (Phase 4)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.widgets.agent_list import AgentList


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    agent_name: str | None = None,
    raw_suffix: str = "20260425143000",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=agent_name,
        raw_suffix=raw_suffix,
    )


def _wire(monkeypatch: Any) -> AgentList:
    widget = AgentList()

    def _call_later(callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(widget, "call_later", _call_later)
    monkeypatch.setattr(widget, "post_message", lambda _msg: None)
    return widget


def _collapse_first_group(
    fold_registry: AgentGroupFoldRegistry, agents: list[Agent]
) -> None:
    from sase.ace.tui.models.agent_groups import build_agent_tree

    tree = build_agent_tree(agents, fold_registry=fold_registry)
    first_group = next(e.group for e in tree if e.group is not None)
    fold_registry.collapse(first_group.group_key)


def test_update_list_populates_row_lookup_maps(monkeypatch: Any) -> None:
    widget = _wire(monkeypatch)
    agents = [_agent(raw_suffix=f"a{i}") for i in range(3)]
    widget.update_list(agents, current_idx=0)

    # Each agent row appears in the lookup maps.
    for i in range(3):
        assert i in widget._row_by_agent_idx
        assert (i, None) in widget._row_by_agent_attempt
        assert widget._row_by_agent_idx[i] == widget._row_by_agent_attempt[(i, None)]

    # Banner rows are not registered as agent rows.
    agent_rows = set(widget._row_by_agent_idx.values())
    for row, entry in enumerate(widget._row_entries):
        if entry[0] >= 0:
            assert row in agent_rows


def test_update_highlight_uses_row_map_no_scan(monkeypatch: Any) -> None:
    widget = _wire(monkeypatch)
    agents = [_agent(raw_suffix=f"a{i}") for i in range(5)]
    widget.update_list(agents, current_idx=0)

    # Sabotage the linear-scan fallback so the test fails if anything
    # other than the row-map lookup is used.
    monkeypatch.setattr(widget, "_row_entries", [], raising=True)

    expected_rows = dict(widget._row_by_agent_idx)
    for agent_idx, expected_row in expected_rows.items():
        widget.update_highlight(agent_idx)
        assert widget.highlighted == expected_row


def test_row_index_for_agent_uses_map(monkeypatch: Any) -> None:
    widget = _wire(monkeypatch)
    agents = [_agent(raw_suffix=f"a{i}") for i in range(4)]
    widget.update_list(agents, current_idx=0)

    expected = dict(widget._row_by_agent_idx)
    monkeypatch.setattr(widget, "_row_entries", [], raising=True)

    for agent_idx, expected_row in expected.items():
        assert widget._row_index_for_agent(agent_idx) == expected_row
    assert widget._row_index_for_agent(99) is None


def test_banner_row_by_key_locates_collapsed_banner(monkeypatch: Any) -> None:
    """Collapsed group banners register in ``_banner_row_by_key`` for O(1) highlight."""
    widget = _wire(monkeypatch)
    fold_registry = AgentGroupFoldRegistry()
    agents = [
        _agent(cl_name="demo-a", project_file="/r/projA/proj.gp", raw_suffix="a"),
        _agent(cl_name="demo-b", project_file="/r/projB/proj.gp", raw_suffix="b"),
    ]
    _collapse_first_group(fold_registry, agents)
    widget.update_list(agents, current_idx=0, fold_registry=fold_registry)

    assert widget._banner_at_row, "expected a collapsed banner row"
    for row, banner in widget._banner_at_row.items():
        assert widget._banner_row_by_key.get(banner.group_key) == row

    # update_highlight via group_key should hit the map and skip the scan.
    target_key, expected_row = next(
        (b.group_key, row) for row, b in widget._banner_at_row.items()
    )
    monkeypatch.setattr(widget, "_banner_at_row", {}, raising=True)
    widget.update_highlight(0, group_key=target_key)
    assert widget.highlighted == expected_row
