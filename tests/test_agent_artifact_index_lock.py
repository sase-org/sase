from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.agent_scan_facade import (
    delete_agent_artifact_index_row,
    query_agent_artifact_index,
)


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
                "schema_version": 1,
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
