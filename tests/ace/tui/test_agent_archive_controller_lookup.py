"""Archive-controller tests: lookup, selection, queued open, and coalescing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
    request_archive_view_load,
    schedule_archive_idle_tick,
)
from sase.ace.tui.actions.agents._archive_controller_build import build_archive_result
from sase.ace.tui.actions.agents._archive_view import (
    open_agents_archive_view_with_query,
)
from sase.ace.tui.models.agent_archive_controller import (
    ARCHIVE_REQUEST_IDLE,
    ArchiveRequestSnapshot,
    ArchiveRevalidationTokens,
    preserve_archive_selected_key,
)
from sase.ace.tui.models.agent_archive_view import (
    ARCHIVE_ARRIVAL_FOUND,
    ARCHIVE_ARRIVAL_MISSING,
    ARCHIVE_ARRIVAL_OWNER,
)
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_controller_helpers import (
    FakeCorpus,
    archive_tokens,
    complete_load,
    instrument,
    make_owner,
)

__all__ = [
    "test_adjacent_selection_fallback",
    "test_coalesced_idle_does_not_publish_false_missing_for_queued_open",
    "test_idle_with_pending_exact_name_does_not_short_circuit_unchanged",
    "test_lookup_miss_clears_pending_and_publishes_missing",
    "test_lookup_owner_of_workflow_child_is_typed",
    "test_lookup_reads_name_from_request_snapshot_not_live_state",
    "test_open_with_query_lookup_selects_row",
    "test_overlapping_idle_rebuilds_coalesce_to_one_in_flight",
    "test_queued_explicit_open_drains_on_idle_tick",
]


@pytest.mark.asyncio
async def test_open_with_query_lookup_selects_row() -> None:
    owner = make_owner()
    spawn, _calls, _facets = instrument(owner)

    with override_flags(agents_archive_view=True):
        open_agents_archive_view_with_query(
            owner, query="in:archive name:bob-cli-5p.4", agent_name="bob-cli-5p.4"
        )
        note_inbox_applied_for_archive(owner, load_state=complete_load())
        await spawn.drain()

    archive = owner._agents_archive_view.archive
    assert archive.selected_key == "bob-cli-5p.4"
    assert archive.pending_exact_name is None
    assert archive.arrival_outcome is not None
    assert archive.arrival_outcome.status == ARCHIVE_ARRIVAL_FOUND
    assert archive.arrival_outcome.requested_name == "bob-cli-5p.4"


def test_adjacent_selection_fallback() -> None:
    assert preserve_archive_selected_key(("a", "b", "c"), "b", ("a", "c", "d")) == "c"
    assert preserve_archive_selected_key(("a", "b"), "b", ("a",)) == "a"
    assert preserve_archive_selected_key(("a",), "gone", ("x", "y")) == "x"
    assert preserve_archive_selected_key(("a",), "a", ()) is None


@pytest.mark.asyncio
async def test_queued_explicit_open_drains_on_idle_tick() -> None:
    owner = make_owner()
    spawn, _calls, _facets = instrument(owner)

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=complete_load())
        await spawn.drain()
        owner._nav_gate.record()
        request_archive_view_load(owner)
        assert owner._agents_archive_controller.explicit_open_queued is True
        assert spawn.coros == []
        owner._nav_gate = NavigationGate()
        schedule_archive_idle_tick(owner)
        assert owner._agents_archive_controller.explicit_open_queued is False
        assert len(spawn.coros) == 1
        await spawn.drain()

    assert spawn.coros == []


@pytest.mark.asyncio
async def test_overlapping_idle_rebuilds_coalesce_to_one_in_flight() -> None:
    owner = make_owner()
    spawn, _calls, _facets = instrument(owner)
    drifted = archive_tokens(digest="profile-2")

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=complete_load())
        await spawn.drain()
        probes: list[int] = []

        def _probe() -> ArchiveRevalidationTokens:
            probes.append(1)
            return drifted

        owner._archive_probe_tokens = _probe
        schedule_archive_idle_tick(owner)
        schedule_archive_idle_tick(owner)
        schedule_archive_idle_tick(owner)
        assert len(spawn.coros) == 1
        await spawn.drain()

    assert len(probes) == 2
    assert spawn.coros == []


@pytest.mark.asyncio
async def test_lookup_miss_clears_pending_and_publishes_missing() -> None:
    owner = make_owner()
    arrivals: list[Any] = []
    owner._archive_arrival_callback = arrivals.append
    spawn, _calls, _facets = instrument(owner)

    with override_flags(agents_archive_view=True):
        open_agents_archive_view_with_query(
            owner, query="in:archive name:ghost", agent_name="ghost"
        )
        note_inbox_applied_for_archive(owner, load_state=complete_load())
        await spawn.drain()

    archive = owner._agents_archive_view.archive
    assert archive.pending_exact_name is None
    assert archive.arrival_outcome is not None
    assert archive.arrival_outcome.status == ARCHIVE_ARRIVAL_MISSING
    assert archive.arrival_outcome.requested_name == "ghost"
    assert arrivals == [archive.arrival_outcome]


@pytest.mark.asyncio
async def test_lookup_owner_of_workflow_child_is_typed() -> None:
    owner = make_owner()
    parent = {"name": "250302.parent", "archive_key": {"source_run_id": "parent-run"}}
    corpus = FakeCorpus(rows=[parent])

    def _lookup(name: str) -> dict[str, Any] | None:
        corpus.lookup_calls.append(name)
        if name in {"step", "250302.step"}:
            return parent
        if name == parent["name"]:
            return parent
        return None

    corpus.lookup = _lookup  # type: ignore[method-assign]
    spawn, _calls, _facets = instrument(owner, corpus=corpus)

    with override_flags(agents_archive_view=True):
        open_agents_archive_view_with_query(
            owner, query="in:archive name:step", agent_name="step"
        )
        note_inbox_applied_for_archive(owner, load_state=complete_load())
        await spawn.drain()

    archive = owner._agents_archive_view.archive
    assert archive.pending_exact_name is None
    assert archive.arrival_outcome is not None
    assert archive.arrival_outcome.status == ARCHIVE_ARRIVAL_OWNER
    assert archive.arrival_outcome.row_name == "250302.parent"
    assert archive.selected_key == "250302.parent"


@pytest.mark.asyncio
async def test_lookup_reads_name_from_request_snapshot_not_live_state() -> None:
    owner = make_owner()
    corpus = FakeCorpus()
    spawn, _calls, _facets = instrument(owner, corpus=corpus)

    with override_flags(agents_archive_view=True):
        open_agents_archive_view_with_query(
            owner, query="in:archive name:bob-cli-5p.4", agent_name="bob-cli-5p.4"
        )
        note_inbox_applied_for_archive(owner, load_state=complete_load())
        owner._agents_archive_view.archive.pending_exact_name = "mutated-after-schedule"
        await spawn.drain()

    assert corpus.lookup_calls == ["bob-cli-5p.4"]
    archive = owner._agents_archive_view.archive
    assert archive.pending_exact_name is None
    assert archive.arrival_outcome is not None
    assert archive.arrival_outcome.status == ARCHIVE_ARRIVAL_FOUND


def test_idle_with_pending_exact_name_does_not_short_circuit_unchanged() -> None:
    owner = make_owner()
    instrument(owner)
    snapshot = ArchiveRequestSnapshot(
        generation=1,
        kind=ARCHIVE_REQUEST_IDLE,
        query="in:archive",
        grouping="day",
        windows=(),
        expanded_containers=(),
        selected_key=None,
        view="archive",
        previous_identities=(),
        link_facets={},
        tokens=archive_tokens(),
        corpus=FakeCorpus(),
        profile=SimpleNamespace(digest="profile-1"),
        pending_exact_name="bob-cli-5p.4",
    )

    result = build_archive_result(owner, snapshot)

    assert result["kind"] != "unchanged"
    assert result.get("lookup_row", {}).get("name") == "bob-cli-5p.4"


@pytest.mark.asyncio
async def test_coalesced_idle_does_not_publish_false_missing_for_queued_open() -> None:
    owner = make_owner()
    arrivals: list[Any] = []
    owner._archive_arrival_callback = arrivals.append
    spawn, _calls, _facets = instrument(owner)

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=complete_load())
        await spawn.drain()
        schedule_archive_idle_tick(owner)
        assert len(spawn.coros) == 1
        schedule_archive_idle_tick(owner)
        assert owner._agents_archive_controller.idle_coalesced is True
        owner._nav_gate.record()
        owner._nav_gate._window_s = 60.0
        open_agents_archive_view_with_query(
            owner, query="in:archive name:bob-cli-5p.4", agent_name="bob-cli-5p.4"
        )
        assert owner._agents_archive_controller.explicit_open_queued is True
        await spawn.release_one()
        assert all(item.status != ARCHIVE_ARRIVAL_MISSING for item in arrivals)
        owner._nav_gate = NavigationGate()
        await spawn.drain()

    archive = owner._agents_archive_view.archive
    assert archive.arrival_outcome is not None
    assert archive.arrival_outcome.status == ARCHIVE_ARRIVAL_FOUND
    assert archive.arrival_outcome.requested_name == "bob-cli-5p.4"
    assert not any(item.status == ARCHIVE_ARRIVAL_MISSING for item in arrivals)
