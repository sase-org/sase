"""Exact-name navigation into the read-only Agents Archive."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.agents._archive_arrival import (
    archive_name_query,
    open_archive_for_agent,
    open_archive_for_archived_row,
)
from sase.ace.tui.models.agent_archive_view import AgentsArchiveViewState
from sase.feature_flags import override_flags


class _Owner:
    def __init__(self) -> None:
        self.current_tab = "artifacts"
        self._agents_archive_view = AgentsArchiveViewState()
        self._link_trail: list[object] = []
        self.notifications: list[tuple[str, str]] = []
        self.saved_positions = 0
        self.switched: list[str] = []

    def _current_link_trail_origin(self) -> str:
        return "origin"

    def _record_link_trail(self, origin: object) -> None:
        self._link_trail.append(origin)

    def _save_current_tab_position(self) -> None:
        self.saved_positions += 1

    def _switch_to_tab(self, tab: str) -> None:
        self.current_tab = tab
        self.switched.append(tab)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


def test_archive_name_query_quotes_exact_name() -> None:
    assert archive_name_query('alice "special"') == (
        'in:archive name:"alice \\"special\\""'
    )


def test_node_finder_archived_row_is_revealed_by_stable_key(monkeypatch) -> None:  # noqa: ANN001
    from sase.ace.tui.actions.agents import _archive_view

    owner = _Owner()
    captured: dict[str, object] = {}

    def open_view(app, *, query):  # noqa: ANN001, ANN202
        captured["query"] = query
        app._agents_archive_view.active_view = "archive"
        app._agents_archive_view.generation += 1
        return SimpleNamespace(
            status="opened",
            generation=app._agents_archive_view.generation,
        )

    monkeypatch.setattr(_archive_view, "open_agents_archive_view_with_query", open_view)
    row = {
        "archive_key": {
            "source_username": "alice",
            "source_machine": "athena",
            "source_run_id": "run-42",
        },
        "container_key": "archive:alice.athena@run-42",
        "agent_name": "worker",
        "last_activity_at": "2026-08-13T12:00:00Z",
    }
    with override_flags(agents_archive_view=True):
        assert open_archive_for_archived_row(owner, row, source="Node Finder")

    archive = owner._agents_archive_view.archive
    assert captured == {"query": "in:archive"}
    assert archive.selected_key == "alice.athena@run-42"
    assert archive.reveal_row == row
    assert owner.notifications == [
        ("Node Finder · opening archived run · read-only", "information")
    ]


def test_exact_archive_arrival_records_one_return_hop_on_hit(monkeypatch) -> None:  # noqa: ANN001
    from sase.ace.tui.actions.agents import _archive_view

    owner = _Owner()
    captured: dict[str, object] = {}

    def open_view(app, *, query, agent_name):  # noqa: ANN001, ANN202
        captured.update(query=query, agent_name=agent_name)
        app._agents_archive_view.active_view = "archive"
        app._agents_archive_view.generation += 1
        app._agents_archive_view.archive.reveal_row = {
            "dismissed_at": "2026-08-13T12:00:00Z"
        }
        return SimpleNamespace(generation=app._agents_archive_view.generation)

    monkeypatch.setattr(_archive_view, "open_agents_archive_view_with_query", open_view)
    with override_flags(agents_archive_view=True):
        assert open_archive_for_agent(owner, "worker", source="From a link")
        assert captured == {
            "query": 'in:archive name:"worker"',
            "agent_name": "worker",
        }
        assert owner.current_tab == "agents"
        owner._archive_arrival_callback(
            SimpleNamespace(status="found", row_name="worker")
        )

    assert owner._link_trail == ["origin"]
    assert len(owner.notifications) == 1
    assert "dismissed Aug 13" in owner.notifications[0][0]
    assert "ctrl+o back" in owner.notifications[0][0]


def test_exact_archive_miss_returns_to_origin_without_adding_trail(
    monkeypatch,
) -> None:  # noqa: ANN001
    from sase.ace.tui.actions.agents import _archive_view

    owner = _Owner()

    def open_view(app, *, query, agent_name):  # noqa: ANN001, ANN202
        del query, agent_name
        app._agents_archive_view.active_view = "archive"
        app._agents_archive_view.generation += 1
        return SimpleNamespace(generation=app._agents_archive_view.generation)

    def close_view(app):  # noqa: ANN001, ANN202
        app._agents_archive_view.active_view = "inbox"

    monkeypatch.setattr(_archive_view, "open_agents_archive_view_with_query", open_view)
    monkeypatch.setattr(_archive_view, "close_agents_archive_view", close_view)
    with override_flags(agents_archive_view=True):
        open_archive_for_agent(
            owner,
            "missing",
            source="From a link",
            return_on_miss=True,
        )
        owner._archive_arrival_callback(
            SimpleNamespace(status="missing", row_name=None)
        )

    assert owner.current_tab == "artifacts"
    assert owner._agents_archive_view.active_view == "inbox"
    assert owner._link_trail == []
    assert owner.notifications == [
        ("agent:missing has no record on this machine", "warning")
    ]
