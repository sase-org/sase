"""Agents-tab committed-query persistence and lifecycle tests."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

from sase.ace.tui.actions.agents._query_persistence import AgentQueryPersistenceMixin
from sase.ace.tui.models import agent_query_persistence as store


class _PersistenceApp(AgentQueryPersistenceMixin):
    def __init__(self) -> None:
        self._agent_search_query = ""
        self._agent_search_query_seeded = False
        self._agent_search_query_seed_attempted = False
        self.notifications: list[str] = []
        self._ensure_agents_query_persistence_state()

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.notifications.append(message)


def test_store_round_trips_nonempty_query_from_sase_home() -> None:
    snapshot = store.make_agent_query_snapshot(
        "status:FAILED",
        dialect=store.DIALECT_UNIFIED,
    )

    store.save_agent_query_snapshot(snapshot)

    result = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)
    assert result.snapshot == snapshot
    assert store._agent_query_state_path().name == store.FILENAME


def test_store_accepts_explicit_empty_across_dialects() -> None:
    snapshot = store.make_agent_query_snapshot("   ", dialect=store.DIALECT_LEGACY)

    store.save_agent_query_snapshot(snapshot)

    result = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)
    assert result.accepted
    assert result.snapshot is not None
    assert result.snapshot.record.source == ""
    assert result.snapshot.record.canonical == ""


def test_store_rejects_nonempty_record_from_other_dialect_without_rewriting() -> None:
    snapshot = store.make_agent_query_snapshot(
        "status:failed",
        dialect=store.DIALECT_LEGACY,
    )
    store.save_agent_query_snapshot(snapshot)
    before = store._agent_query_state_path().read_bytes()

    result = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)

    assert result.snapshot is None
    assert result.warning is not None
    assert "legacy dialect" in result.warning
    assert store._agent_query_state_path().read_bytes() == before


def test_store_rejects_oversized_and_invalid_files_without_rewriting() -> None:
    path = store._agent_query_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{" + b"x" * store.MAX_FILE_BYTES)

    oversized = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)

    assert oversized.snapshot is None
    assert oversized.warning is not None
    assert path.read_bytes() == b"{" + b"x" * store.MAX_FILE_BYTES

    path.write_bytes(b"\xff")
    invalid_utf8 = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)

    assert invalid_utf8.snapshot is None
    assert invalid_utf8.warning is not None
    assert path.read_bytes() == b"\xff"


def test_atomic_write_failure_preserves_existing_complete_record(
    monkeypatch,
) -> None:
    old = store.make_agent_query_snapshot(
        "status:RUNNING", dialect=store.DIALECT_UNIFIED
    )
    new = store.make_agent_query_snapshot(
        "status:FAILED", dialect=store.DIALECT_UNIFIED
    )
    store.save_agent_query_snapshot(old)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("boom")

    monkeypatch.setattr(store, "_replace_state_file", fail_replace)

    try:
        store.save_agent_query_snapshot(new)
    except OSError:
        pass
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("save should fail")

    result = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)
    assert result.snapshot == old
    assert (
        list(store._agent_query_state_path().parent.glob(f".{store.FILENAME}.*.tmp"))
        == []
    )


def test_restore_result_sets_baseline_and_suppresses_future_seed() -> None:
    app = _PersistenceApp()
    snapshot = store.make_agent_query_snapshot("", dialect=store.DIALECT_LEGACY)
    result = store.AgentQueryLoadResult(snapshot=snapshot)

    assert app._apply_agents_query_restore_result(result, generation=0)

    assert app._agent_search_query == ""
    assert app._agent_search_query_seed_attempted is True
    assert app._agents_query_durable_snapshot == snapshot
    assert app._agents_query_save_pending is None


def test_new_commit_wins_over_older_restore_result() -> None:
    app = _PersistenceApp()
    restore = store.AgentQueryLoadResult(
        snapshot=store.make_agent_query_snapshot(
            "status:FAILED",
            dialect=store.DIALECT_UNIFIED,
        )
    )

    app._record_explicit_agents_query_commit("status:RUNNING")

    assert not app._apply_agents_query_restore_result(restore, generation=0)
    assert app._agent_search_query == "status:RUNNING"
    assert app._agent_search_query_seed_attempted is True


async def test_writer_coalesces_to_latest_pending_snapshot() -> None:
    app = _PersistenceApp()
    started = threading.Event()
    release = threading.Event()
    saved_sources: list[str] = []

    def save(snapshot: store.AgentQuerySnapshot) -> None:
        if not saved_sources:
            started.set()
            assert release.wait(timeout=5)
        saved_sources.append(snapshot.record.source)
        store.save_agent_query_snapshot(snapshot)

    app._save_agents_query_snapshot_now = save  # type: ignore[method-assign]

    app._record_explicit_agents_query_commit("status:RUNNING")
    assert await _wait_thread_event(started)
    app._record_explicit_agents_query_commit("status:FAILED")
    app._record_explicit_agents_query_commit("   ")
    release.set()

    await app._flush_agents_query_state()

    assert saved_sources[-1] == ""
    result = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)
    assert result.snapshot is not None
    assert result.snapshot.record.source == ""


async def test_flush_retries_latest_failed_save_once() -> None:
    app = _PersistenceApp()
    calls = 0

    def flaky_save(snapshot: store.AgentQuerySnapshot) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary")
        store.save_agent_query_snapshot(snapshot)

    app._save_agents_query_snapshot_now = flaky_save  # type: ignore[method-assign]

    app._record_explicit_agents_query_commit("status:FAILED")
    await app._flush_agents_query_state()

    assert calls == 2
    assert app._agents_query_dirty_snapshot is None
    result = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)
    assert result.snapshot is not None
    assert result.snapshot.record.source == "status:FAILED"


async def test_idle_restored_app_does_not_replace_newer_external_write() -> None:
    first = store.make_agent_query_snapshot(
        "status:RUNNING",
        dialect=store.DIALECT_UNIFIED,
    )
    second = store.make_agent_query_snapshot(
        "status:FAILED",
        dialect=store.DIALECT_UNIFIED,
    )
    store.save_agent_query_snapshot(first)
    app = _PersistenceApp()
    loaded = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)
    assert app._apply_agents_query_restore_result(loaded, generation=0)

    store.save_agent_query_snapshot(second)
    await app._flush_agents_query_state()

    current = json.loads(store._agent_query_state_path().read_text())
    assert current["record"]["source"] == "status:FAILED"


async def _wait_thread_event(event: threading.Event) -> bool:
    import asyncio

    return await asyncio.wait_for(asyncio.to_thread(event.wait, 5), timeout=5)
