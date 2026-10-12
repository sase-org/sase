"""Shared fakes and fixtures for the split archive-controller tests.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_view import init_agents_archive_view_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_controller import ArchiveRevalidationTokens
from sase.ace.tui.util.nav_gate import NavigationGate

__all__ = [
    "FakeCached",
    "FakeCorpus",
    "PendingSpawn",
    "archive_tokens",
    "bounded_load",
    "complete_load",
    "instrument",
    "make_agent",
    "make_owner",
]


def make_agent(name: str, status: str = "DONE") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=None,
        workflow="crs",
    )


def complete_load() -> SimpleNamespace:
    return SimpleNamespace(
        complete_history=True,
        artifact_source="full",
        bounded_prefix=False,
        complete_visible_inbox=True,
        truncated=False,
        query_incomplete=False,
    )


def bounded_load() -> SimpleNamespace:
    return SimpleNamespace(
        complete_history=False,
        artifact_source="full",
        bounded_prefix=True,
        complete_visible_inbox=False,
        truncated=False,
        query_incomplete=False,
    )


def archive_tokens(
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


class FakeCorpus:
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


class FakeCached:
    def __init__(self, corpus: FakeCorpus, digest: str = "profile-1") -> None:
        self.corpus = corpus
        self.profile = SimpleNamespace(digest=digest)


class _FakeTask:
    def __init__(self, spawn: PendingSpawn) -> None:
        self._spawn = spawn

    def cancel(self) -> None:
        self._spawn.cancelled += 1


class PendingSpawn:
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


def make_owner(*, agents: list[Agent] | None = None) -> SimpleNamespace:
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


def instrument(
    owner: SimpleNamespace,
    *,
    corpus: FakeCorpus | None = None,
    tokens: ArchiveRevalidationTokens | None = None,
    get_corpus: Any = None,
) -> tuple[PendingSpawn, list[Any], list[Any]]:
    spawn = PendingSpawn()
    owner._archive_spawn = spawn
    compile_calls: list[Any] = []
    facet_calls: list[Any] = []
    resolved = corpus or FakeCorpus()
    cached = FakeCached(resolved)

    def _get(**kwargs: Any) -> FakeCached:
        compile_calls.append(kwargs)
        if get_corpus is not None:
            return get_corpus(**kwargs)
        return cached

    owner._archive_get_corpus = _get
    owner._archive_probe_tokens = lambda: tokens or archive_tokens()
    owner._archive_load_facets = lambda: facet_calls.append("facets") or {"agent": {}}
    owner._archive_profile = SimpleNamespace(digest="profile-1")
    owner._archive_load_display_snapshot = lambda: None
    return spawn, compile_calls, facet_calls
