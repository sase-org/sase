"""Exact-name navigation into the read-only Agents Archive."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.agents._archive_arrival import (
    _archive_name_query,
    open_archive_for_agent,
    open_archive_for_archived_row,
)
from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
)
from sase.ace.tui.models.agent_archive_view import AgentsArchiveViewState
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_controller_helpers import (
    FakeCached,
    FakeCorpus,
    archive_tokens,
    complete_load,
    instrument,
    make_owner,
)


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
    assert _archive_name_query('alice "special"') == (
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
    assert open_archive_for_archived_row(owner, row, source="Node Finder")

    archive = owner._agents_archive_view.archive
    assert captured == {"query": "in:archive"}
    assert archive.selected_key == "alice.athena@run-42"
    assert archive.reveal_row == row
    assert owner.notifications == [
        ("Node Finder · opening archived run · read-only", "information")
    ]


def _arrival_owner(*, tab: str = "artifacts") -> SimpleNamespace:
    """Instrumented owner with tab-switch fakes for arrival tests."""
    owner = make_owner()
    owner.current_tab = tab
    owner.saved_positions = 0
    owner.switched: list[str] = []
    owner.notifications: list[tuple[str, str]] = []
    owner._link_trail: list[object] = []

    def _save() -> None:
        owner.saved_positions += 1

    def _switch(tab_name: str) -> None:
        owner.current_tab = tab_name
        owner.switched.append(tab_name)

    owner._save_current_tab_position = _save
    owner._switch_to_tab = _switch
    owner._current_link_trail_origin = lambda: "origin"  # noqa: E731
    owner._record_link_trail = owner._link_trail.append
    owner.notify = lambda message, **kwargs: owner.notifications.append(  # noqa: E731
        (message, kwargs.get("severity", "information"))
    )
    return owner


@pytest.mark.asyncio
async def test_lookup_first_hit_opens_archive_and_records_one_hop() -> None:
    owner = _arrival_owner()
    worker = {
        "name": "worker",
        "archive_key": {"source_run_id": "1"},
        "dismissed_at": "2026-08-13T12:00:00Z",
    }
    spawn, _calls, _facets = instrument(owner, corpus=FakeCorpus(rows=[worker]))
    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()

    assert open_archive_for_agent(owner, "worker", source="From a link") is True
    # The exact lookup runs first: nothing opens before it resolves.
    assert owner.current_tab == "artifacts"
    assert owner._agents_archive_view.active_view == "inbox"
    await spawn.drain()

    archive = owner._agents_archive_view.archive
    assert archive.committed_query == 'in:archive name:"worker"'
    assert archive.selected_key == "worker"
    assert owner.current_tab == "agents"
    assert owner._link_trail == ["origin"]
    assert len(owner.notifications) == 1
    assert "dismissed Aug 13" in owner.notifications[0][0]
    assert "ctrl+o back" in owner.notifications[0][0]


@pytest.mark.asyncio
async def test_lookup_first_miss_toasts_and_changes_nothing() -> None:
    owner = _arrival_owner()
    spawn, _calls, _facets = instrument(
        owner, corpus=FakeCorpus(rows=[{"name": "other", "archive_key": {}}])
    )
    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()
    owner._agents_archive_view.archive.committed_query = "in:archive status:x"
    owner._agents_archive_view.archive.selected_key = "old"

    open_archive_for_agent(
        owner,
        "missing",
        source="From a link",
        return_on_miss=True,
    )
    await spawn.drain()

    assert owner.current_tab == "artifacts"
    assert owner._agents_archive_view.active_view == "inbox"
    assert owner._agents_archive_view.archive.committed_query == "in:archive status:x"
    assert owner._agents_archive_view.archive.selected_key == "old"
    assert owner._link_trail == []
    assert owner.notifications == [
        ("agent:missing has no record on this machine", "warning")
    ]


@pytest.mark.asyncio
async def test_post_lookup_race_miss_returns_to_origin_without_adding_trail(
    monkeypatch,
) -> None:  # noqa: ANN001
    from sase.ace.tui.actions.agents import _archive_view

    owner = _arrival_owner()
    worker = {"name": "worker", "archive_key": {"source_run_id": "1"}}
    spawn, _calls, _facets = instrument(owner, corpus=FakeCorpus(rows=[worker]))
    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()

    def close_view(app):  # noqa: ANN001, ANN202
        app._agents_archive_view.active_view = "inbox"

    monkeypatch.setattr(_archive_view, "close_agents_archive_view", close_view)
    open_archive_for_agent(
        owner,
        "worker",
        source="From a link",
        return_on_miss=True,
    )
    # The pre-lookup hits, then the corpus drifts before the open resolves.
    await spawn.release_one()
    assert owner._agents_archive_view.active_view == "archive"
    owner._archive_get_corpus = lambda **kwargs: FakeCached(FakeCorpus(rows=[]))  # noqa: E731
    owner._archive_probe_tokens = lambda: archive_tokens(digest="profile-2")  # noqa: E731
    await spawn.drain()

    assert owner.current_tab == "artifacts"
    assert owner._agents_archive_view.active_view == "inbox"
    assert owner._link_trail == []
    assert owner.notifications == [
        ("agent:worker has no record on this machine", "warning")
    ]
