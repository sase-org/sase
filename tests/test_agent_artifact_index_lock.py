from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_lock import (
    agent_artifact_index_operation_lock,
    try_agent_artifact_index_operation_lock,
)
from sase.core.agent_scan_facade import (
    agent_artifact_index_status,
    delete_agent_artifact_index_row,
    query_agent_artifact_index,
    read_agent_artifact_index_meta,
    write_agent_artifact_index_meta,
)
from sase.core.agent_scan_wire import AGENT_SCAN_WIRE_SCHEMA_VERSION


def test_artifact_index_operation_lock_allows_nested_facade_call(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def fake_require(name: str) -> Callable[..., dict[str, Any]]:
        assert name == "delete_agent_artifact_index_row"

        def fake_delete(index_path: str, artifact_dir: str) -> dict[str, Any]:
            calls.append(f"{index_path}:{artifact_dir}")
            return {
                "schema_version": 3,
                "index_path": index_path,
                "rows_deleted": 1,
            }

        return fake_delete

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.require_rust_binding", fake_require
    )

    with agent_artifact_index_operation_lock():
        update = delete_agent_artifact_index_row(
            tmp_path / "index.sqlite",
            tmp_path / "artifact",
        )

    assert update.rows_deleted == 1
    assert calls == [f"{tmp_path / 'index.sqlite'}:{tmp_path / 'artifact'}"]


def test_artifact_index_facade_calls_serialize_before_entering_rust(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    entered_rust = threading.Event()
    results: list[int] = []
    errors: list[Exception] = []

    def fake_require(name: str) -> Callable[..., dict[str, Any]]:
        assert name == "query_agent_artifact_index"

        def fake_query(
            index_path: str,
            projects_root: str,
            query: dict[str, Any],
            options: dict[str, Any],
        ) -> dict[str, Any]:
            del index_path, query, options
            entered_rust.set()
            return {
                "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
                "projects_root": projects_root,
                "stats": {},
                "options": {},
                "records": [],
            }

        return fake_query

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.require_rust_binding", fake_require
    )

    def run_query() -> None:
        try:
            snapshot = query_agent_artifact_index(
                tmp_path / "index.sqlite",
                tmp_path / "projects",
            )
            results.append(len(snapshot.records))
        except Exception as exc:  # pragma: no cover - assertion re-raised below
            errors.append(exc)

    with agent_artifact_index_operation_lock():
        thread = threading.Thread(target=run_query, daemon=True)
        thread.start()
        assert not entered_rust.wait(timeout=0.05)

    assert entered_rust.wait(timeout=1.0)
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert errors == []
    assert results == [0]


def test_artifact_index_read_metadata_facade_calls_serialize_before_entering_rust(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    entered_rust = threading.Event()
    results: list[str | None] = []
    errors: list[Exception] = []

    def fake_require(name: str) -> Callable[..., object]:
        assert name == "read_agent_artifact_index_meta"

        def fake_read(index_path: str, key: str) -> str:
            del index_path, key
            entered_rust.set()
            return "stored"

        return fake_read

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.require_rust_binding", fake_require
    )

    def run_metadata_calls() -> None:
        try:
            results.append(
                read_agent_artifact_index_meta(
                    tmp_path / "index.sqlite",
                    "dismissed_projection",
                )
            )
        except Exception as exc:  # pragma: no cover - assertion re-raised below
            errors.append(exc)

    with agent_artifact_index_operation_lock():
        thread = threading.Thread(target=run_metadata_calls, daemon=True)
        thread.start()
        assert not entered_rust.wait(timeout=0.05)

    assert entered_rust.wait(timeout=1.0)
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert errors == []
    assert results == ["stored"]


def test_artifact_index_write_metadata_facade_calls_serialize_before_entering_rust(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    entered_rust = threading.Event()
    results: list[str] = []
    errors: list[Exception] = []

    def fake_require(name: str) -> Callable[..., None]:
        assert name == "write_agent_artifact_index_meta"

        def fake_write(index_path: str, key: str, value: str) -> None:
            del index_path, key, value
            entered_rust.set()

        return fake_write

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.require_rust_binding", fake_require
    )

    def run_write() -> None:
        try:
            write_agent_artifact_index_meta(
                tmp_path / "index.sqlite",
                "dismissed_projection",
                "{}",
            )
            results.append("written")
        except Exception as exc:  # pragma: no cover - assertion re-raised below
            errors.append(exc)

    with agent_artifact_index_operation_lock():
        thread = threading.Thread(target=run_write, daemon=True)
        thread.start()
        assert not entered_rust.wait(timeout=0.05)

    assert entered_rust.wait(timeout=1.0)
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert errors == []
    assert results == ["written"]


def test_artifact_index_status_facade_calls_serialize_before_entering_rust(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    entered_rust = threading.Event()
    results: list[int] = []
    errors: list[Exception] = []

    def fake_require(name: str) -> Callable[..., dict[str, Any]]:
        assert name == "agent_artifact_index_status"

        def fake_status(index_path: str) -> dict[str, Any]:
            entered_rust.set()
            return {
                "schema_version": 3,
                "index_path": index_path,
                "agent_artifacts_rows": 7,
                "dismissed_agents_rows": 2,
            }

        return fake_status

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.require_rust_binding", fake_require
    )

    def run_status() -> None:
        try:
            status = agent_artifact_index_status(tmp_path / "index.sqlite")
            results.append(status.agent_artifacts_rows)
        except Exception as exc:  # pragma: no cover - assertion re-raised below
            errors.append(exc)

    with agent_artifact_index_operation_lock():
        thread = threading.Thread(target=run_status, daemon=True)
        thread.start()
        assert not entered_rust.wait(timeout=0.05)

    assert entered_rust.wait(timeout=1.0)
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert errors == []
    assert results == [7]


def test_bounded_operation_lock_reports_contention() -> None:
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with agent_artifact_index_operation_lock():
            acquired.set()
            release.wait(timeout=1.0)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    assert acquired.wait(timeout=1.0)
    try:
        with try_agent_artifact_index_operation_lock(0.01) as entered:
            assert entered is False
    finally:
        release.set()
        thread.join(timeout=1.0)

    assert not thread.is_alive()
