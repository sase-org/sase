"""Tests for app-level link subject cache helpers."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions import link_subject as link_subject_actions
from sase.ace.tui.actions.link_subject import LinkSubjectMixin
from sase.ace.tui.relations.link_index import LinkChip, LinkIndex
from sase.ace.tui.relations.link_subject import LinkSubject
from sase.core.artifact_entry_target import ArtifactEntryTarget


def _chip() -> LinkChip:
    return LinkChip(
        relation="implements",
        label="implements",
        directed=True,
        this_is_source=True,
        neighbor_ref="bead:sase-uv.2",
        neighbor_target=ArtifactEntryTarget("beads", ("sase", "task", "sase-uv.2")),
        accent="#D787FF",
        icon="*",
        why="",
        origin="manual",
        uses=1,
        created_by="test",
        created_at="2026-08-27T00:00:00Z",
        writable=True,
    )


class _AvailabilityApp(LinkSubjectMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = (
            SimpleNamespace(agent_name="agent-a", identity=("agent-a",)),
            SimpleNamespace(agent_name="agent-b", identity=("agent-b",)),
        )
        self._link_index = LinkIndex(
            by_ref={"agent:agent-a": (_chip(),)},
            targets_by_ref={},
            source_key=("test",),
        )
        self._link_index_errors = ()
        self._link_index_loading = False
        self._link_index_pending = False
        self._link_index_generation = 1
        self._link_subject_cache = None
        self._link_follow_available_cache = None
        self._link_rail_refresh_scheduled = False
        self.scheduled_sources: list[str] = []

    def _get_selected_agent(self) -> object | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _schedule_link_index_refresh(self, *, source: str) -> None:
        self.scheduled_sources.append(source)


def test_link_follow_availability_recomputes_only_on_selection_or_index_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _AvailabilityApp()
    selected_calls: list[int] = []

    def _selected(app_obj: _AvailabilityApp) -> LinkSubject | None:
        selected_calls.append(app_obj.current_idx)
        agent = app_obj._get_selected_agent()
        if agent is None:
            return None
        name = str(getattr(agent, "agent_name", ""))
        return LinkSubject(
            ref=f"agent:{name}",
            target=ArtifactEntryTarget("agents", (name,)),
            accent="#0062FF",
            icon="*",
        )

    monkeypatch.setattr(link_subject_actions, "selected_link_subject", _selected)

    assert app.link_follow_available_for_selection() is True
    assert app.link_follow_available_for_selection() is True
    assert selected_calls == [0]

    app.current_idx = 1
    assert app.link_follow_available_for_selection() is False
    assert selected_calls == [0, 1]

    app._link_index_generation += 1
    assert app.link_follow_available_for_selection() is False
    assert selected_calls == [0, 1, 1]


def test_link_subject_cache_shared_by_availability_edges_and_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _AvailabilityApp()
    selected_calls: list[int] = []

    def _selected(app_obj: _AvailabilityApp) -> LinkSubject:
        selected_calls.append(app_obj.current_idx)
        return LinkSubject(
            ref="agent:agent-a",
            target=ArtifactEntryTarget("agents", ("agent-a",)),
            accent="#0062FF",
            icon="*",
        )

    monkeypatch.setattr(link_subject_actions, "selected_link_subject", _selected)

    assert app.link_follow_available_for_selection() is True
    assert len(app.link_edges_for_selection()) == 1
    assert app.link_subject_for_selection() is not None
    assert selected_calls == [0]


class _RailRefreshApp(LinkSubjectMixin):
    def __init__(self) -> None:
        self._link_rail_refresh_scheduled = False
        self.callbacks: list[Callable[[], None]] = []
        self.refreshed = 0

    def call_after_refresh(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)

    def _refresh_link_rail_now(self) -> None:
        self._link_rail_refresh_scheduled = False
        self.refreshed += 1


def test_refresh_link_rail_coalesces_repeated_requests_in_one_tick() -> None:
    app = _RailRefreshApp()

    app.refresh_link_rail()
    app.refresh_link_rail()
    app.refresh_link_rail()

    assert len(app.callbacks) == 1
    assert app.refreshed == 0
    callback = app.callbacks.pop()
    callback()
    assert app.refreshed == 1

    app.refresh_link_rail()
    assert len(app.callbacks) == 1
