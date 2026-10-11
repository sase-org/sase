"""Corpus-controller tests: generations, prewarm gate, idle ticks, failures.

Blocked workers and injected probes prove last-request-wins rejection,
cancellation, warm-handle reuse, no compile before the Inbox gate, no
catalog scan on quiet ticks, and an unaffected Inbox when the index is
missing or unreadable.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._archive_controller import (
    archive_corpus_is_warm,
    archive_corpus_snapshot,
    archive_inbox_pulse,
    cancel_archive_controller,
    init_agents_archive_controller,
    note_inbox_applied_for_archive,
    request_archive_lookup,
    request_archive_view_load,
    request_archive_windows,
    schedule_archive_idle_tick,
)
from sase.ace.tui.actions.agents._archive_view import (
    init_agents_archive_view_state,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_controller import (
    ARCHIVE_CORPUS_LOADING,
    ARCHIVE_CORPUS_MISSING,
    ARCHIVE_CORPUS_UNREADABLE,
    ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    ARCHIVE_CORPUS_WARM,
    ArchivePageWindow,
    ArchiveRevalidationTokens,
    preserve_archive_selected_key,
)
from sase.ace.tui.models.agent_archive_view import AGENTS_VIEW_INBOX
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.feature_flags import override_flags


def _agent(name: str, status: str = "DONE") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=None,
        workflow="crs",
    )


def _complete_load() -> SimpleNamespace:
    return SimpleNamespace(
        complete_history=True,
        artifact_source="full",
        bounded_prefix=False,
        complete_visible_inbox=True,
        truncated=False,
        query_incomplete=False,
    )


def _bounded_load() -> SimpleNamespace:
    return SimpleNamespace(
        complete_history=False,
        artifact_source="full",
        bounded_prefix=True,
        complete_visible_inbox=False,
        truncated=False,
        query_incomplete=False,
    )


def _tokens(
    *, digest: str = "profile-1", rebuilding: bool = False
) -> ArchiveRevalidationTokens:
    return ArchiveRevalidationTokens(
        index_exists=True,
        index_stat=(1, 2),
        link_signature=(("proj", 1, 2),),
        profile_digest=digest,
        rebuilding=rebuilding,
        indexed_rows=4 if rebuilding else 0,
    )


class _FakeCorpus:
    def __init__(
        self,
        *,
        status: str = "ok",
        rows: list[dict[str, Any]] | None = None,
        indexed_rows: int = 0,
    ) -> None:
        self.status = status
        self.wire = {"status": {"status": status, "indexed_rows": indexed_rows}}
        self.rows_spec = rows or [
            {"name": "bob-cli-5p.4", "archive_key": {"source_run_id": "1"}}
        ]
        self.summary_calls = 0
        self.rows_calls = 0
        self.lookup_calls: list[str] = []

    def summary(
        self, query: str, *, group_by: str, profile: Any = None
    ) -> dict[str, Any]:
        self.summary_calls += 1
        return {
            "total": len(self.rows_spec),
            "groups": [{"key": "2025-01-01", "count": len(self.rows_spec)}],
        }

    def rows(self, query: str, **kwargs: Any) -> dict[str, Any]:
        self.rows_calls += 1
        return {"rows": list(self.rows_spec), "total": len(self.rows_spec)}

    def lookup(self, name: str) -> dict[str, Any] | None:
        self.lookup_calls.append(name)
        for row in self.rows_spec:
            if row.get("name") == name:
                return row
        return None

    def count(self, query: str, profile: Any = None) -> int:
        return len(self.rows_spec)


class _FakeCached:
    def __init__(self, corpus: _FakeCorpus, digest: str = "profile-1") -> None:
        self.corpus = corpus
        self.profile = SimpleNamespace(digest=digest)


class _FakeTask:
    def __init__(self, spawn: _PendingSpawn) -> None:
        self._spawn = spawn

    def cancel(self) -> None:
        self._spawn.cancelled += 1


class _PendingSpawn:
    def __init__(self) -> None:
        self.coros: list[Any] = []
        self.cancelled = 0

    def __call__(self, owner: Any, coro: Any, **kwargs: Any) -> Any:
        self.coros.append(coro)
        return _FakeTask(self)

    async def release_one(self) -> None:
        await self.coros.pop(0)

    async def drain(self) -> None:
        while self.coros:
            await self.release_one()


async def _immediate(fn: Any) -> Any:
    return fn()


def _owner(*, agents: list[Agent] | None = None) -> SimpleNamespace:
    owner = SimpleNamespace()
    owner._agents = list(agents or [])
    owner._unread_completed_agent_ids = set()
    owner._pending_attention_count = 0
    owner._nav_gate = NavigationGate()
    owner._prompt_input_active = lambda: False
    owner._agent_search_query = ""
    owner.current_idx = 0
    owner._schedule_calls: list[str] = []
    owner._archive_corpus_root = "/tmp/archive-test"
    owner._archive_run_off_thread = _immediate
    init_agents_archive_view_state(owner)

    def _schedule(*, source: str = "unknown", **kwargs: Any) -> None:
        owner._schedule_calls.append(source)

    owner._schedule_agents_async_refresh = _schedule
    return owner


def _instrument(
    owner: SimpleNamespace,
    *,
    corpus: _FakeCorpus | None = None,
    tokens: ArchiveRevalidationTokens | None = None,
    get_corpus: Any = None,
) -> tuple[_PendingSpawn, list[Any], list[Any]]:
    spawn = _PendingSpawn()
    owner._archive_spawn = spawn
    compile_calls: list[Any] = []
    facet_calls: list[Any] = []
    resolved = corpus or _FakeCorpus()
    cached = _FakeCached(resolved)

    def _get(**kwargs: Any) -> _FakeCached:
        compile_calls.append(kwargs)
        if get_corpus is not None:
            return get_corpus(**kwargs)
        return cached

    owner._archive_get_corpus = _get
    owner._archive_probe_tokens = lambda: tokens or _tokens()
    owner._archive_load_facets = lambda: facet_calls.append("facets") or {"agent": {}}
    owner._archive_profile = SimpleNamespace(digest="profile-1")
    return spawn, compile_calls, facet_calls


def test_flag_off_never_probes_or_prewarms() -> None:
    owner = _owner(agents=[_agent("live")])
    spawn, compile_calls, facet_calls = _instrument(owner)

    with override_flags():
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        schedule_archive_idle_tick(owner)
        request_archive_view_load(owner)
        outcome = open_agents_archive_view(owner)

    assert outcome.status == "disabled"
    assert outcome.view == AGENTS_VIEW_INBOX
    assert compile_calls == []
    assert facet_calls == []
    assert spawn.coros == []
    assert owner._agents[0].cl_name == "live"
    assert archive_corpus_snapshot(owner).status == "cold"


def test_bounded_inbox_load_does_not_open_prewarm_gate() -> None:
    owner = _owner(agents=[_agent("live")])
    spawn, compile_calls, _facets = _instrument(owner)

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=_bounded_load())
        schedule_archive_idle_tick(owner)

    assert compile_calls == []
    assert spawn.coros == []
    assert archive_corpus_snapshot(owner).status == "cold"


@pytest.mark.asyncio
async def test_early_open_paints_loading_and_queues_until_gate() -> None:
    owner = _owner(agents=[_agent("live")])
    spawn, compile_calls, _facets = _instrument(owner)

    with override_flags(agents_archive_view=True):
        outcome = open_agents_archive_view(owner)
        assert outcome.status == "opened"
        assert archive_corpus_snapshot(owner).status == ARCHIVE_CORPUS_LOADING
        assert compile_calls == []
        assert owner._schedule_calls == ["archive_prewarm_gate"]

        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        assert compile_calls == []
        await spawn.drain()

    assert compile_calls
    assert archive_corpus_is_warm(owner)
    assert owner._agents[0].cl_name == "live"


@pytest.mark.asyncio
async def test_complete_idle_prewarms_once_and_idle_tick_skips_compile() -> None:
    owner = _owner(agents=[_agent("live", "RUNNING")])
    spawn, compile_calls, facet_calls = _instrument(owner)

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        assert spawn.coros
        await spawn.drain()
        assert len(compile_calls) == 1
        assert facet_calls == ["facets"]
        pulse = archive_inbox_pulse(owner)
        assert pulse.total == 1
        assert pulse.running == 1

        schedule_archive_idle_tick(owner)
        await spawn.drain()

    assert len(compile_calls) == 1
    assert facet_calls == ["facets"]
    assert archive_corpus_snapshot(owner).status == ARCHIVE_CORPUS_WARM


@pytest.mark.asyncio
async def test_prewarm_waits_for_idle_ui() -> None:
    owner = _owner()
    spawn, compile_calls, _facets = _instrument(owner)
    owner._nav_gate.record()

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        assert spawn.coros == []
        owner._nav_gate = NavigationGate()
        schedule_archive_idle_tick(owner)
        await spawn.drain()

    assert compile_calls


@pytest.mark.asyncio
async def test_prompt_typing_defers_idle_requery() -> None:
    owner = _owner()
    spawn, compile_calls, _facets = _instrument(owner)

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        await spawn.drain()
        owner._prompt_input_active = lambda: True
        schedule_archive_idle_tick(owner)

    assert spawn.coros == []
    assert len(compile_calls) == 1


@pytest.mark.asyncio
async def test_stale_generation_is_dropped() -> None:
    owner = _owner()
    spawn, compile_calls, _facets = _instrument(owner)
    first = _FakeCorpus(rows=[{"name": "old-row"}])
    second = _FakeCorpus(rows=[{"name": "new-row"}])
    results = [_FakeCached(first), _FakeCached(second)]

    def _get(**kwargs: Any) -> _FakeCached:
        compile_calls.append(kwargs)
        return results.pop(0)

    owner._archive_get_corpus = _get

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(owner)
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
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
    owner = _owner()
    spawn, compile_calls, _facets = _instrument(owner)

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        assert spawn.coros
        cancel_archive_controller(owner)
        assert spawn.cancelled == 1
        spawn.coros[0].close()
        spawn.coros.clear()

    assert compile_calls == []
    assert archive_corpus_snapshot(owner).status == ARCHIVE_CORPUS_LOADING


@pytest.mark.asyncio
async def test_query_reuses_warm_handle_without_facet_reload() -> None:
    owner = _owner()
    spawn, compile_calls, facet_calls = _instrument(owner)

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
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
    owner = _owner()
    corpus = _FakeCorpus(
        rows=[
            {"name": "keep-me"},
            {"name": "neighbor"},
        ]
    )
    spawn, compile_calls, facet_calls = _instrument(owner, corpus=corpus)
    drifted = _tokens(digest="profile-2")

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(owner)
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
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
    owner = _owner()
    spawn, compile_calls, facet_calls = _instrument(owner)
    link_drift = ArchiveRevalidationTokens(
        index_exists=True,
        index_stat=(1, 2),
        link_signature=(("proj", 9, 9),),
        profile_digest="profile-1",
        rebuilding=False,
        indexed_rows=0,
    )

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        await spawn.drain()
        owner._archive_probe_tokens = lambda: link_drift
        schedule_archive_idle_tick(owner)
        await spawn.drain()

    assert len(compile_calls) == 2
    assert facet_calls == ["facets", "facets"]


@pytest.mark.asyncio
async def test_missing_index_is_honest_and_leaves_inbox_alone() -> None:
    owner = _owner(agents=[_agent("inbox-live", "RUNNING")])
    missing = _FakeCorpus(status="missing", rows=[])
    spawn, _calls, _facets = _instrument(owner, corpus=missing)
    owner._archive_probe_tokens = lambda: ArchiveRevalidationTokens(
        index_exists=False,
        index_stat=None,
        link_signature=(),
        profile_digest="profile-1",
        rebuilding=False,
        indexed_rows=0,
    )

    with override_flags(agents_archive_view=True):
        inbox_before = list(owner._agents)
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        await spawn.drain()

    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.status == ARCHIVE_CORPUS_MISSING
    assert snapshot.error_message == ARCHIVE_INDEX_UNAVAILABLE_MESSAGE
    assert owner._agents == inbox_before
    assert owner._agents[0].status == "RUNNING"


@pytest.mark.asyncio
async def test_unreadable_index_publishes_rebuild_hint() -> None:
    owner = _owner(agents=[_agent("inbox-live")])
    spawn, _calls, _facets = _instrument(owner)
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

    with override_flags(agents_archive_view=True):
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        await spawn.drain()

    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.status == ARCHIVE_CORPUS_UNREADABLE
    assert snapshot.error_message == ARCHIVE_INDEX_UNAVAILABLE_MESSAGE
    assert owner._agents[0].cl_name == "inbox-live"


@pytest.mark.asyncio
async def test_rebuilding_index_serves_rows_and_progress() -> None:
    owner = _owner()
    corpus = _FakeCorpus(
        status="rebuilding",
        rows=[{"name": "partial-row"}],
        indexed_rows=12,
    )
    spawn, _calls, _facets = _instrument(
        owner, corpus=corpus, tokens=_tokens(rebuilding=True)
    )

    with override_flags(agents_archive_view=True):
        request_archive_windows(
            owner, [ArchivePageWindow(group_key="2025-01-01", offset=0, limit=100)]
        )
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        await spawn.drain()

    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.status == "rebuilding"
    assert snapshot.indexed_rows == 12
    assert snapshot.identities == ("partial-row",)
    assert snapshot.error_message is None


@pytest.mark.asyncio
async def test_lookup_selects_exact_name_and_clears_pending() -> None:
    owner = _owner()
    spawn, compile_calls, _facets = _instrument(owner)

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(owner)
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        await spawn.drain()
        request_archive_lookup(owner, "bob-cli-5p.4")
        await spawn.drain()

    assert owner._agents_archive_view.archive.selected_key == "bob-cli-5p.4"
    assert owner._agents_archive_view.archive.pending_exact_name is None
    assert len(compile_calls) == 1


@pytest.mark.asyncio
async def test_open_with_query_lookup_selects_row() -> None:
    owner = _owner()
    spawn, _calls, _facets = _instrument(owner)

    with override_flags(agents_archive_view=True):
        open_agents_archive_view_with_query(
            owner, query="in:archive name:bob-cli-5p.4", agent_name="bob-cli-5p.4"
        )
        note_inbox_applied_for_archive(owner, load_state=_complete_load())
        await spawn.drain()

    assert owner._agents_archive_view.archive.selected_key == "bob-cli-5p.4"
    assert owner._agents_archive_view.archive.pending_exact_name is None


def test_adjacent_selection_fallback() -> None:
    assert preserve_archive_selected_key(("a", "b", "c"), "b", ("a", "c", "d")) == "c"
    assert preserve_archive_selected_key(("a", "b"), "b", ("a",)) == "a"
    assert preserve_archive_selected_key(("a",), "gone", ("x", "y")) == "x"
    assert preserve_archive_selected_key(("a",), "a", ()) is None


def test_init_controller_is_cold() -> None:
    owner = SimpleNamespace()
    init_agents_archive_controller(owner)
    snapshot = archive_corpus_snapshot(owner)
    assert snapshot.status == "cold"
    assert snapshot.warm is False
    assert snapshot.generation == 0
