"""Healer failed-row enumeration: the index window matches the artifact scan."""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Any

import pytest

import sase.core.agent_artifact_index_recent as recent
import sase.core.agent_scan_facade as facade
from sase.agent.auto_restart import healer_target_rows as rows
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)
from sase.core.time import get_timezone

NOW = time.time()
_DAY = 86400.0


def _row(
    home: Path,
    *,
    started: float,
    name: str,
    outcome: str = "failed",
    finished: float | None = None,
    hidden: bool = False,
    project: str = "sase",
) -> Path:
    stamp = datetime.datetime.fromtimestamp(started, tz=get_timezone()).strftime(
        "%Y%m%d%H%M%S"
    )
    artifact_dir = (
        home / ".sase" / "projects" / project / "artifacts" / "ace-run" / stamp
    )
    artifact_dir.mkdir(parents=True)
    meta: dict[str, Any] = {"name": name}
    if hidden:
        meta["hidden"] = True
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    done = {
        "outcome": outcome,
        "name": name,
        "error": f"{name} broke",
        "finished_at": started + 60 if finished is None else finished,
    }
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    return artifact_dir


def _keys(found: list[Any]) -> list[tuple[str, str, str, float | None]]:
    return sorted(
        (str(row.artifacts_dir), row.project, row.agent_name, row.died_at)
        for row in found
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    lookback = rows.HISTORY_LOOKBACK_SECONDS
    _row(tmp_path, started=NOW - _DAY, name="failed-recent")
    _row(tmp_path, started=NOW - 2 * _DAY, name="failed-hidden", hidden=True)
    _row(tmp_path, started=NOW - 3 * _DAY, name="failed-other", project="other")
    _row(tmp_path, started=NOW - _DAY / 2, name="completed", outcome="completed")
    _row(tmp_path, started=NOW - lookback - _DAY, name="failed-old")
    # Started before the lookback, finished inside it: the scan's start-stamp
    # bound excludes it, and the index window must too.
    _row(
        tmp_path,
        started=NOW - lookback - _DAY / 2,
        name="failed-long-run",
        finished=NOW - _DAY,
    )
    return tmp_path


def _build_index(home: Path) -> None:
    rebuild_agent_artifact_index(
        default_agent_artifact_index_path(), home / ".sase" / "projects"
    )


def test_index_window_matches_artifact_scan(home: Path) -> None:
    _build_index(home)

    from_index = rows._rows_via_index(now=NOW)

    assert from_index is not None
    assert _keys(from_index) == _keys(rows._rows_via_scan(now=NOW))
    assert sorted(row.agent_name for row in from_index) == [
        "failed-hidden",
        "failed-other",
        "failed-recent",
    ]


def test_recent_failure_rows_reads_index_without_walking(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_index(home)
    queries: list[Any] = []
    original = recent.query_agent_artifact_index_payload

    def recording(index_path: Any, projects_root: Any, query: Any, options: Any) -> Any:
        queries.append(query)
        return original(index_path, projects_root, query, options)

    monkeypatch.setattr(recent, "query_agent_artifact_index_payload", recording)
    monkeypatch.setattr(
        facade,
        "scan_agent_artifacts",
        lambda *_a, **_k: pytest.fail("the index path must not walk artifacts"),
    )

    found = rows.recent_failure_rows(now=NOW)

    assert len(found) == 3
    assert queries
    assert not any(query.include_full_history for query in queries)
    assert not any(query.include_active for query in queries)
    assert all(query.include_hidden for query in queries)


@pytest.mark.usefixtures("home")
def test_recent_failure_rows_scans_when_index_is_missing() -> None:
    assert not default_agent_artifact_index_path().exists()

    found = rows.recent_failure_rows(now=NOW)

    assert _keys(found) == _keys(rows._rows_via_scan(now=NOW))
    assert len(found) == 3


def test_recent_failure_rows_scans_when_index_query_fails(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_index(home)

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(recent, "query_agent_artifact_index_payload", broken)

    found = rows.recent_failure_rows(now=NOW)

    assert sorted(row.agent_name for row in found) == [
        "failed-hidden",
        "failed-other",
        "failed-recent",
    ]
