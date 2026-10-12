"""Archive-controller tests: generations, cancel, reuse, drift, and failures."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._archive_controller import (
    archive_corpus_snapshot,
    cancel_archive_controller,
    init_agents_archive_controller,
    note_inbox_applied_for_archive,
    request_archive_windows,
    schedule_archive_idle_tick,
)
from sase.ace.tui.actions.agents._archive_view import open_agents_archive_view
from sase.ace.tui.models.agent_archive_controller import (
    ARCHIVE_CORPUS_LOADING,
    ARCHIVE_CORPUS_MISSING,
    ARCHIVE_CORPUS_UNREADABLE,
    ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    ArchivePageWindow,
    ArchiveRevalidationTokens,
)
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_controller_helpers import (
    FakeCached,
    FakeCorpus,
    archive_tokens,
    complete_load,
    instrument,
    make_agent,
    make_owner,
)

__all__ = [
    "test_cancel_drops_blocked_worker",
    "test_init_controller_is_cold",
    "test_input_drift_rebuilds_and_keeps_selection",
    "test_link_signature_drift_reloads_facets",
    "test_missing_index_is_honest_and_leaves_inbox_alone",
    "test_probe_error_publishes_unavailable_and_unwedges_idle",
    "test_query_reuses_warm_handle_without_facet_reload",
    "test_rebuilding_index_serves_rows_and_progress",
    "test_stale_generation_is_dropped",
    "test_unreadable_index_publishes_rebuild_hint",
    "test_worker_publishes_display_snapshot_for_project_banners",
]


@pytest.mark.asyncio
async def test_stale_generation_is_dropped() -> None:
    owner = make_owner()
    spawn, compile_calls, _facets = instrument(owner)
    first = FakeCorpus(rows=[{"name": "old-row"}])
    second = FakeCorpus(rows=[{"name": "new-row"}])
    results = [FakeCached(first), FakeCached(second)]

    def _get(**kwargs: Any) -> FakeCached:
        compile_calls.append(kwargs)
        return results.pop(0)

    owner._archive_get_corpus = _get

    open_agents_archive_view(owner)
    note_inbox_applied_for_archive(owner, load_state=complete_load())
    first_coro = spawn.coros.pop(0)
    request_archive_windows(
        owner, [ArchivePageWindow(group_key="2025-01-01", offset=0, limit=100)]
    )
    await first_coro
    assert archive_corpus_snapshot(owner).identities != ("old-row",)
    await spawn.drain()

    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.identities == ("new-row",)
    assert owner._agents_archive_view.archive.selected_key == "new-row"


@pytest.mark.asyncio
async def test_cancel_drops_blocked_worker() -> None:
    owner = make_owner()
    spawn, compile_calls, _facets = instrument(owner)

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    assert spawn.coros
    cancel_archive_controller(owner)
    assert spawn.cancelled == 1
    spawn.coros[0].close()
    spawn.coros.clear()

    assert compile_calls == []
    assert archive_corpus_snapshot(owner).status == ARCHIVE_CORPUS_LOADING


@pytest.mark.asyncio
async def test_query_reuses_warm_handle_without_facet_reload() -> None:
    owner = make_owner()
    spawn, compile_calls, facet_calls = instrument(owner)

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()
    request_archive_windows(
        owner, [ArchivePageWindow(group_key="2025-01-01", offset=0, limit=100)]
    )
    await spawn.drain()

    assert len(compile_calls) == 1
    assert facet_calls == ["facets"]
    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.windows
    assert snapshot.identities == ("bob-cli-5p.4",)


@pytest.mark.asyncio
async def test_input_drift_rebuilds_and_keeps_selection() -> None:
    owner = make_owner()
    corpus = FakeCorpus(
        rows=[
            {"name": "keep-me"},
            {"name": "neighbor"},
        ]
    )
    spawn, compile_calls, facet_calls = instrument(owner, corpus=corpus)
    drifted = archive_tokens(digest="profile-2")

    open_agents_archive_view(owner)
    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()
    owner._agents_archive_view.archive.selected_key = "keep-me"
    request_archive_windows(
        owner, [ArchivePageWindow(group_key="2025-01-01", offset=0, limit=100)]
    )
    await spawn.drain()
    owner._archive_probe_tokens = lambda: drifted
    schedule_archive_idle_tick(owner)
    await spawn.drain()

    assert len(compile_calls) == 2
    assert facet_calls == ["facets"]
    assert owner._agents_archive_view.archive.selected_key == "keep-me"


@pytest.mark.asyncio
async def test_link_signature_drift_reloads_facets() -> None:
    owner = make_owner()
    spawn, compile_calls, facet_calls = instrument(owner)
    link_drift = ArchiveRevalidationTokens(
        index_exists=True,
        index_stat=(1, 2),
        link_signature=(("proj", 9, 9),),
        profile_digest="profile-1",
        rebuilding=False,
        indexed_rows=0,
    )

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()
    owner._archive_probe_tokens = lambda: link_drift
    schedule_archive_idle_tick(owner)
    await spawn.drain()

    assert len(compile_calls) == 2
    assert facet_calls == ["facets", "facets"]


@pytest.mark.asyncio
async def test_missing_index_is_honest_and_leaves_inbox_alone() -> None:
    owner = make_owner(agents=[make_agent("inbox-live", "RUNNING")])
    missing = FakeCorpus(status="missing", rows=[])
    spawn, _calls, _facets = instrument(owner, corpus=missing)
    owner._archive_probe_tokens = lambda: ArchiveRevalidationTokens(
        index_exists=False,
        index_stat=None,
        link_signature=(),
        profile_digest="profile-1",
        rebuilding=False,
        indexed_rows=0,
    )

    inbox_before = list(owner._agents)
    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()

    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.status == ARCHIVE_CORPUS_MISSING
    assert snapshot.error_message == ARCHIVE_INDEX_UNAVAILABLE_MESSAGE
    assert owner._agents == inbox_before
    assert owner._agents[0].status == "RUNNING"


@pytest.mark.asyncio
async def test_unreadable_index_publishes_rebuild_hint() -> None:
    owner = make_owner(agents=[make_agent("inbox-live")])
    spawn, _calls, _facets = instrument(owner)
    owner._archive_get_corpus = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("corrupt")
    )
    owner._archive_probe_tokens = lambda: ArchiveRevalidationTokens(
        index_exists=True,
        index_stat=None,
        link_signature=(),
        profile_digest="profile-1",
        rebuilding=False,
        indexed_rows=0,
    )

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()

    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.status == ARCHIVE_CORPUS_UNREADABLE
    assert snapshot.error_message == ARCHIVE_INDEX_UNAVAILABLE_MESSAGE
    assert owner._agents[0].cl_name == "inbox-live"


@pytest.mark.asyncio
async def test_rebuilding_index_serves_rows_and_progress() -> None:
    owner = make_owner()
    corpus = FakeCorpus(
        status="rebuilding",
        rows=[{"name": "partial-row"}],
        indexed_rows=12,
    )
    spawn, _calls, _facets = instrument(
        owner, corpus=corpus, tokens=archive_tokens(rebuilding=True)
    )

    request_archive_windows(
        owner, [ArchivePageWindow(group_key="2025-01-01", offset=0, limit=100)]
    )
    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()

    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.status == "rebuilding"
    assert snapshot.indexed_rows == 12
    assert snapshot.identities == ("partial-row",)
    assert snapshot.error_message is None


def test_init_controller_is_cold() -> None:
    owner = SimpleNamespace()
    init_agents_archive_controller(owner)
    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.status == "cold"
    assert snapshot.warm is False
    assert snapshot.generation == 0


@pytest.mark.asyncio
async def test_probe_error_publishes_unavailable_and_unwedges_idle() -> None:
    owner = make_owner()
    spawn, _calls, _facets = instrument(owner)

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()
    owner._archive_probe_tokens = lambda: (_ for _ in ()).throw(
        RuntimeError("probe failed")
    )
    schedule_archive_idle_tick(owner)
    await spawn.drain()

    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.refreshing is False
    assert snapshot.status == ARCHIVE_CORPUS_UNREADABLE
    assert snapshot.error_message == ARCHIVE_INDEX_UNAVAILABLE_MESSAGE

    schedule_archive_idle_tick(owner)

    assert spawn.coros, "idle tick must keep scheduling after a worker error"


@pytest.mark.asyncio
async def test_worker_publishes_display_snapshot_for_project_banners() -> None:
    owner = make_owner()
    snapshot = object()
    spawn, _calls, _facets = instrument(owner)
    owner._archive_load_display_snapshot = lambda: snapshot

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()

    assert archive_corpus_snapshot(owner).display_snapshot is snapshot
