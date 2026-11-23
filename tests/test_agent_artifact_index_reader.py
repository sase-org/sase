"""Owned index results reuse records without sharing them between consumers."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.agent_scan_facade import rebuild_agent_artifact_index
from sase.core.agent_scan_index_queries import (
    AgentArtifactIndexReader,
    query_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)

_QUERY = AgentArtifactIndexQueryWire(
    include_active=True,
    include_recent_completed=False,
    active_limit=None,
    freshness="revalidate",
)


@pytest.fixture
def index_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "projects"
    artifact = root / "proj" / "artifacts" / "ace-run" / "20261123000000"
    artifact.mkdir(parents=True)
    marker = artifact / "agent_meta.json"
    marker.write_text(json.dumps({"name": "original", "wait_for": ["parent"]}))
    index = tmp_path / "index.sqlite"
    rebuild_agent_artifact_index(index, root)
    return index, root, marker


def test_unchanged_records_skip_hydration_but_refresh_status(
    index_fixture: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.agent_scan_index_reader as adapter

    index, root, _ = index_fixture
    reader = AgentArtifactIndexReader()
    first = reader.query(index, root, _QUERY)
    assert first is not None
    original = adapter.agent_scan_wire_from_dict
    hydrated_rows: list[int] = []

    def recording(payload: dict[str, Any]) -> Any:
        hydrated_rows.append(len(payload["records"]))
        return original(payload)

    monkeypatch.setattr(adapter, "agent_scan_wire_from_dict", recording)
    second = reader.query(index, root, _QUERY)
    assert second is not None
    assert hydrated_rows == [0]
    assert second.records is first.records
    assert second.stats.record_json_decoded == 0
    assert second.stats.marker_signatures_checked >= 1
    assert second.stats is not first.stats
    assert second.clan_context is not first.clan_context


def test_independent_readers_and_public_mutable_calls_are_detached(
    index_fixture: tuple[Path, Path, Path],
) -> None:
    index, root, _ = index_fixture
    first = AgentArtifactIndexReader().query(index, root, _QUERY)
    second = AgentArtifactIndexReader().query(index, root, _QUERY)
    public = query_agent_artifact_index(index, root, _QUERY)
    assert first is not None and second is not None
    assert first.records[0].agent_meta is not None
    assert second.records[0].agent_meta is not None
    assert public.records[0].agent_meta is not None
    first.records[0].agent_meta.wait_for.append("local mutation")
    public.records[0].agent_meta.wait_for.clear()
    assert second.records[0].agent_meta.wait_for == ["parent"]
    fresh = query_agent_artifact_index(index, root, _QUERY)
    assert fresh.records[0].agent_meta is not None
    assert fresh.records[0].agent_meta.wait_for == ["parent"]


def test_changed_marker_repairs_and_replaces_owned_records(
    index_fixture: tuple[Path, Path, Path],
) -> None:
    index, root, marker = index_fixture
    reader = AgentArtifactIndexReader()
    first = reader.query(index, root, _QUERY)
    marker.write_text(json.dumps({"name": "changed-and-longer"}))
    changed = reader.query(index, root, _QUERY)
    assert first is not None and changed is not None
    assert changed.records is not first.records
    assert changed.records[0].agent_meta is not None
    assert changed.records[0].agent_meta.name == "changed-and-longer"
    assert changed.stats.rows_repaired == 1
    warm = reader.query(index, root, _QUERY)
    unchanged = reader.query(index, root, _QUERY)
    assert warm is not None and unchanged is not None
    assert unchanged.records is warm.records


def test_query_identity_and_native_eviction_force_materialization(
    index_fixture: tuple[Path, Path, Path],
) -> None:
    index, root, _ = index_fixture
    reader = AgentArtifactIndexReader()
    first = reader.query(index, root, _QUERY)
    # Production native cache retains eight identities. Other consumers may
    # evict ours; the stale token must produce fresh records rather than empty.
    other = AgentArtifactIndexReader()
    for limit in range(12):
        other.query(
            index, root, _QUERY, AgentArtifactScanOptionsWire(max_records=limit)
        )
    after = reader.query(index, root, _QUERY)
    assert first is not None and after is not None
    assert after.records == first.records
    assert after.records is not first.records
    changed = reader.query(
        index, root, _QUERY, AgentArtifactScanOptionsWire(only_projects=("elsewhere",))
    )
    assert changed is not None and changed.records == []
    back = reader.query(index, root, _QUERY)
    assert back is not None and len(back.records) == 1


def test_bounded_lock_busy_does_not_call_native_or_report_unchanged(
    index_fixture: tuple[Path, Path, Path],
) -> None:
    index, root, _ = index_fixture
    reader = AgentArtifactIndexReader()
    first = reader.query(index, root, _QUERY)
    held, release = Event(), Event()

    def hold() -> None:
        with agent_artifact_index_operation_lock():
            held.set()
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(hold)
        assert held.wait(5)
        try:
            assert reader.query(index, root, _QUERY, lock_timeout_seconds=0) is None
        finally:
            release.set()
        future.result()
    after = reader.query(index, root, _QUERY)
    assert first is not None and after is not None
    assert after.records is first.records


def test_binding_failure_clears_owned_generation_before_retry(
    index_fixture: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.agent_scan_index_reader as adapter

    index, root, _ = index_fixture
    reader = AgentArtifactIndexReader()
    first = reader.query(index, root, _QUERY)
    original = adapter.require_rust_binding

    def failing(*_args: Any) -> Any:
        raise RuntimeError("injected native failure")

    with monkeypatch.context() as patch:
        patch.setattr(adapter, "require_rust_binding", failing)
        with pytest.raises(RuntimeError, match="injected"):
            reader.query(index, root, _QUERY)
    tokens: list[int | None] = []

    def binding(name: str) -> Any:
        native = original(name)

        def recording(*args: Any) -> Any:
            tokens.append(args[-1])
            return native(*args)

        return recording

    monkeypatch.setattr(adapter, "require_rust_binding", binding)
    after = reader.query(index, root, _QUERY)
    assert tokens == [None]
    assert first is not None and after is not None
    assert first.records == after.records
    assert first.records is not after.records


def test_parallel_readers_do_not_share_python_objects(
    index_fixture: tuple[Path, Path, Path],
) -> None:
    index, root, _ = index_fixture

    def read() -> Any:
        return AgentArtifactIndexReader().query(index, root, _QUERY)

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = list(executor.map(lambda _: read(), range(2)))
    assert a.records == b.records
    assert a.records[0] is not b.records[0]


@pytest.mark.parametrize("failure", ["bad_generation", "decoder"])
def test_invalid_response_never_certifies_owned_records(
    index_fixture: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    import sase.core.agent_scan_index_reader as adapter

    index, root, _ = index_fixture
    reader = AgentArtifactIndexReader()
    first = reader.query(index, root, _QUERY)
    original = adapter.require_rust_binding

    def require(name: str) -> Any:
        native = original(name)

        def bad(*args: Any) -> Any:
            result = native(*args)
            if failure == "bad_generation":
                result["payload_generation"] = None
                result["records_reused"] = True
            else:
                result["snapshot"]["schema_version"] = -1
            return result

        return bad

    with monkeypatch.context() as patch:
        patch.setattr(adapter, "require_rust_binding", require)
        with pytest.raises(ValueError):
            reader.query(index, root, _QUERY)
    after = reader.query(index, root, _QUERY)
    assert first is not None and after is not None
    assert after.records == first.records
    assert after.records is not first.records


def test_external_commit_after_read_is_seen_on_next_validation(
    index_fixture: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    import sase.core.agent_scan_index_reader as adapter

    index, root, _ = index_fixture
    reader = AgentArtifactIndexReader()
    first = reader.query(index, root, _QUERY)
    validated, release = Event(), Event()
    original = adapter.require_rust_binding

    def require(name: str) -> Any:
        native = original(name)

        def paused(*args: Any) -> Any:
            response = native(*args)
            validated.set()
            assert release.wait(5)
            return response

        return paused

    with ThreadPoolExecutor(max_workers=1) as executor:
        with monkeypatch.context() as patch:
            patch.setattr(adapter, "require_rust_binding", require)
            future = executor.submit(reader.query, index, root, _QUERY)
            assert validated.wait(5)
            try:
                # A separate writer does not take the Python operation lock.
                with sqlite3.connect(index) as conn:
                    raw = conn.execute(
                        "SELECT record_json FROM agent_artifacts"
                    ).fetchone()[0]
                    record = json.loads(raw)
                    record["agent_meta"]["name"] = "concurrent-index-change"
                    conn.execute(
                        "UPDATE agent_artifacts SET record_json = ?",
                        (json.dumps(record),),
                    )
            finally:
                release.set()
            prior = future.result()
    current = reader.query(index, root, _QUERY)
    assert first is not None and prior is not None and current is not None
    assert prior.records is first.records
    assert current.records is not first.records
    assert current.records[0].agent_meta is not None
    assert current.records[0].agent_meta.name == "concurrent-index-change"
