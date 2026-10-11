"""Shared fakes for the Archive column tests: a model corpus, widget, and owner.

``ModelCorpus`` emulates the Rust corpus contract the Archive list depends on:
summary counts presentation *roots* per day group, ``rows`` flattens roots
(plus members of expanded containers) and reports the flattened ``total``, and
``limit=0`` probes the total without rows.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, UTC
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_view import init_agents_archive_view_state
from sase.ace.tui.models.agent_archive_controller import ArchiveRevalidationTokens
from sase.ace.tui.util.nav_gate import NavigationGate

NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


def light_row(
    run: str,
    *,
    day: str = "2026-10-10",
    hour: int = 12,
    name: str | None = None,
    container_key: str | None = None,
    outcome: str = "done",
    status: str = "DONE",
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "archive_key": {
            "source_username": "u",
            "source_machine": "m",
            "source_run_id": run,
        },
        "container_key": container_key or f"archive:u.m@{run}",
        "container": False,
        "member_count": 1,
        "agent_name": name or f"agent-{run}",
        "status": status,
        "outcome": outcome,
        "model": "claude-opus-4",
        "provider": "claude",
        "project": "sase",
        "last_activity_at": f"{day}T{hour:02d}:00:00Z",
        "time_basis": "ended",
        "start_time": f"{day}T{hour:02d}:00:00Z",
        "runtime_seconds": 60,
        "restorable": True,
    }
    row.update(extra)
    return row


class ModelCorpus:
    """Minimal in-memory stand-in for ``AgentArchiveCorpus``."""

    status = "ok"
    timezone = "UTC"

    def __init__(self, rows: list[dict[str, Any]], *, status: str = "ok") -> None:
        self.status = status
        self.wire = {"status": {"status": status, "indexed_rows": len(rows)}}
        self.all_rows = rows
        self.summary_calls = 0
        self.rows_calls: list[dict[str, Any]] = []
        self.queries: list[str] = []

    # -- helpers -------------------------------------------------------------

    def _roots(self) -> list[tuple[str, Any]]:
        by_container: dict[str, list[dict[str, Any]]] = {}
        for row in self.all_rows:
            by_container.setdefault(row["container_key"], []).append(row)
        roots: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for row in self.all_rows:
            members = by_container[row["container_key"]]
            if len(members) >= 2:
                if row["container_key"] not in seen:
                    seen.add(row["container_key"])
                    roots.append(("container", members))
            else:
                roots.append(("member", row))
        return roots

    @staticmethod
    def _day(row: Mapping[str, Any]) -> str:
        stamp = row.get("last_activity_at")
        return str(stamp)[:10] if stamp else ""

    def _root_group(self, kind: str, payload: Any, group_by: str) -> str:
        row = payload[0] if kind == "container" else payload
        if group_by == "day":
            return self._day(row)
        if group_by == "project":
            return str(row.get("project") or "")
        if group_by == "model":
            return str(row.get("model") or "")
        return str(row.get("outcome") or "")

    # -- corpus contract -----------------------------------------------------

    def summary(self, query: str, *, group_by: str, profile: Any = None):
        self.summary_calls += 1
        self.queries.append(query)
        groups: dict[str, int] = {}
        for kind, payload in self._roots():
            key = self._root_group(kind, payload, group_by)
            groups[key] = groups.get(key, 0) + 1
        return {
            "total": sum(groups.values()),
            "groups": [{"key": key, "count": count} for key, count in groups.items()],
        }

    def rows(
        self,
        query: str,
        *,
        group_by: str,
        group_key: str,
        offset: int,
        limit: int,
        expanded_container_keys: Any = (),
        profile: Any = None,
    ) -> dict[str, Any]:
        self.rows_calls.append(
            {
                "group_key": group_key,
                "offset": offset,
                "limit": limit,
                "expanded": tuple(expanded_container_keys),
            }
        )
        self.queries.append(query)
        flattened: list[dict[str, Any]] = []
        for kind, payload in self._roots():
            if self._root_group(kind, payload, group_by) != group_key:
                continue
            if kind == "member":
                flattened.append(dict(payload))
                continue
            newest = payload[0]
            container = dict(newest)
            container.update(
                container=True,
                member_count=len(payload),
                agent_name=newest["container_key"].split(":", 1)[-1],
            )
            flattened.append(container)
            if newest["container_key"] in tuple(expanded_container_keys):
                flattened.extend(dict(member) for member in payload)
        start = min(offset, len(flattened))
        return {
            "rows": flattened[start : start + limit],
            "offset": offset,
            "limit": limit,
            "total": len(flattened),
        }

    def lookup(self, name: str) -> dict[str, Any] | None:
        for row in self.all_rows:
            if row.get("agent_name") == name:
                return dict(row)
        return None

    def count(self, query: str, profile: Any = None) -> int:
        self.queries.append(query)
        return len(self._roots())


class FakeColumnWidget:
    """Records every call the glue makes on the mounted column."""

    def __init__(self) -> None:
        self.paints: list[dict[str, Any]] = []
        self.cursors: list[str | None] = []
        self.sections: list[str] = []
        self.pulses: list[Any] = []
        self.reveals = 0

    def apply_items(
        self, items: Any, cursor_key: str | None, *, tz: Any, grouping: str
    ):
        self.paints.append(
            {
                "items": tuple(items),
                "cursor": cursor_key,
                "tz": tz,
                "grouping": grouping,
            }
        )

    def set_cursor(self, key: str | None) -> None:
        self.cursors.append(key)

    def set_section(self, section: str) -> None:
        self.sections.append(section)

    def set_pulse(self, pulse: Any) -> None:
        self.pulses.append(pulse)

    def reveal_cursor(self) -> None:
        self.reveals += 1

    @property
    def last_items(self) -> tuple[Any, ...]:
        return self.paints[-1]["items"]

    def last_labels(self) -> list[str]:
        """Compact per-item descriptions of the latest paint."""
        out = []
        for item in self.last_items:
            if item.kind == "banner":
                out.append(f"{'v' if item.open else '>'} {item.label} ({item.count})")
            elif item.kind == "tail":
                out.append(f"tail {item.remaining}")
            elif item.kind in {"loading", "message"}:
                out.append(f"~ {item.label}")
            else:
                out.append(item.key)
        return out


class FakeDebouncer:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []
        self.cancelled = 0

    def schedule(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)

    def cancel(self) -> None:
        self.cancelled += 1

    def fire(self) -> None:
        callback = self.callbacks[-1]
        self.callbacks.clear()
        callback()


class _FakeTask:
    def cancel(self) -> None:
        return


class PendingSpawn:
    """Collects controller coroutines so tests release them deterministically."""

    def __init__(self) -> None:
        self.coros: list[Any] = []

    def __call__(self, owner: Any, coro: Any, **kwargs: Any) -> Any:
        self.coros.append(coro)
        return _FakeTask()

    async def drain(self) -> int:
        count = 0
        while self.coros:
            await self.coros.pop(0)
            count += 1
        return count


async def _immediate(fn: Callable[[], Any]) -> Any:
    return fn()


def complete_load() -> SimpleNamespace:
    return SimpleNamespace(
        complete_history=True,
        artifact_source="full",
        bounded_prefix=False,
        complete_visible_inbox=True,
        truncated=False,
        query_incomplete=False,
    )


def tokens(
    *, rebuilding: bool = False, indexed_rows: int = 0
) -> ArchiveRevalidationTokens:
    return ArchiveRevalidationTokens(
        index_exists=True,
        index_stat=(1, 2),
        link_signature=(("proj", 1, 2),),
        profile_digest="profile-1",
        rebuilding=rebuilding,
        indexed_rows=indexed_rows,
    )


class ColumnHarness:
    """A duck-typed app wired to a model corpus, fake widget, and fake spawn."""

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        status: str = "ok",
        corpus: Any = None,
    ) -> None:
        from sase.ace.tui.actions.agents._archive_controller import (
            note_inbox_applied_for_archive,
        )

        self.corpus = corpus if corpus is not None else ModelCorpus(rows, status=status)
        owner = SimpleNamespace()
        owner._agents = []
        owner._unread_completed_agent_ids = set()
        owner._pending_attention_count = 0
        owner._nav_gate = NavigationGate()
        owner._prompt_input_active = lambda: False
        owner._agent_search_query = ""
        owner.current_idx = 0
        owner.current_tab = "agents"
        owner._archive_corpus_root = "/tmp/archive-column-test"
        owner._archive_run_off_thread = _immediate
        owner._archive_now = lambda: NOW
        owner._agent_detail_debouncer = FakeDebouncer()
        owner._schedule_calls = []
        owner._schedule_agents_async_refresh = lambda **kw: (
            owner._schedule_calls.append(kw)
        )
        init_agents_archive_view_state(owner)
        self.spawn = PendingSpawn()
        owner._archive_spawn = self.spawn
        # A real corpus needs the real compiled profile; fakes take a stub.
        profile: Any = SimpleNamespace(digest="profile-1")
        if corpus is not None:
            from sase.core.agent_archive_facade import agents_archive_profile

            profile = agents_archive_profile()
        owner._archive_get_corpus = lambda **kwargs: SimpleNamespace(
            corpus=self.corpus, profile=profile
        )
        owner._archive_probe_tokens = lambda: tokens(
            rebuilding=status == "rebuilding",
            indexed_rows=len(rows) if status == "rebuilding" else 0,
        )
        owner._archive_load_facets = lambda: {}
        owner._archive_profile = profile
        self.widget = FakeColumnWidget()
        owner._archive_column_widget = self.widget
        self.owner = owner
        self.note_inbox_applied = lambda: note_inbox_applied_for_archive(
            owner, load_state=complete_load()
        )

    @property
    def archive(self) -> Any:
        return self.owner._agents_archive_view.archive

    async def settle(self) -> int:
        """Release every pending controller task until the system is quiet."""
        total = 0
        while True:
            drained = await self.spawn.drain()
            if not drained:
                return total
            total += drained
