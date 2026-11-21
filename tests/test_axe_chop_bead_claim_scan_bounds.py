"""bead_claim_checks owner pre-pass: bounded index reads and the hourly full sweep.

The filesystem walk (``SASE_CHOP_SCAN_FULL_WALK=1``) is the ground truth for
release and acquire decisions. A bounded tick must reach the same decisions
for every owner inside its window, and the full-history sweep must reach the
same decisions for every owner.
"""

from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

import sase.core.agent_artifact_index_recent as recent
import sase.scripts.sase_chop_bead_claim_checks as claim_checks
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)
from sase.core.process_identity import process_identity_token
from sase.scripts._chop_bead_claim_scan import (
    BEAD_CLAIM_RECONCILED_MARKER,
    CLAIM_FULL_SWEEP_INTERVAL_SECONDS,
    claim_full_sweep_due,
    record_claim_full_sweep,
)
from sase.scripts._chop_incremental_index import CLAIM_RECENT_WINDOW_SECONDS
from tests._agent_names_fixtures import DEAD_PID
from tests._axe_chop_bead_claim_checks_helpers import make_runtime

FULL_WALK_ENV = "SASE_CHOP_SCAN_FULL_WALK"
NOW = time.time()
_HOUR = 3600.0


def _stamp(at: float) -> str:
    return datetime.datetime.fromtimestamp(at).strftime("%Y%m%d%H%M%S")


def _owner(
    home: Path,
    *,
    started: float,
    name: str,
    promoted: bool | None = False,
    alive: bool = False,
    finished: float | None = None,
    hidden: bool = False,
    waiting: bool = False,
    claim_marker: bool = False,
    tombstoned: bool = False,
) -> Path:
    artifact_dir = (
        home / ".sase" / "projects" / "sase" / "artifacts" / "ace-run" / _stamp(started)
    )
    artifact_dir.mkdir(parents=True)
    pid = os.getpid() if alive else DEAD_PID
    meta: dict[str, Any] = {"name": name, "bead_id": f"bead-{name}", "pid": pid}
    if alive:
        meta["process_identity"] = process_identity_token(pid)
    if promoted is not None:
        meta["bead_claim_promoted"] = promoted
    if hidden:
        meta["hidden"] = True
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if finished is not None:
        done = {"outcome": "completed", "name": name, "finished_at": finished}
        (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    if waiting:
        (artifact_dir / "waiting.json").write_text(
            json.dumps({"waiting_for": ["dep"]}), encoding="utf-8"
        )
    if claim_marker:
        (artifact_dir / "bead_claim.json").write_text("{}\n", encoding="utf-8")
    if tombstoned:
        (artifact_dir / BEAD_CLAIM_RECONCILED_MARKER).write_text(
            "{}\n", encoding="utf-8"
        )
    return artifact_dir


def _build_index(home: Path) -> None:
    rebuild_agent_artifact_index(
        default_agent_artifact_index_path(), home / ".sase" / "projects"
    )


def _decisions(
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
    mode: str,
) -> tuple[set[str], set[str]]:
    """Return (release, acquire) owner names the pre-pass would act on."""

    monkeypatch.delenv(FULL_WALK_ENV, raising=False)
    if mode == "walk":
        monkeypatch.setenv(FULL_WALK_ENV, "1")
    elif mode == "bounded":
        record_claim_full_sweep(NOW)
    elif mode == "sweep":
        record_claim_full_sweep(NOW - 2 * CLAIM_FULL_SWEEP_INTERVAL_SECONDS)
    claims = claim_checks._prepass_claim_artifacts(home / ".sase" / "projects", now=NOW)
    release: set[str] = set()
    acquire: set[str] = set()
    for record in claim_checks._latest_owner_records(claims).values():
        if record.bead_claim_promoted is not False or record.has_reconcile_tombstone:
            continue
        if record.is_alive:
            if not record.has_bead_claim_marker:
                acquire.add(record.agent_name)
        else:
            release.add(record.agent_name)
    return release, acquire


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv(FULL_WALK_ENV, raising=False)
    return tmp_path


def test_bounded_tick_matches_full_walk_for_owners_in_window(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner(home, started=NOW - 2 * _HOUR, name="crashed")
    _owner(home, started=NOW - 3 * _HOUR, name="waiter", alive=True, waiting=True)
    _owner(
        home,
        started=NOW - 4 * _HOUR,
        name="claimed-waiter",
        alive=True,
        waiting=True,
        claim_marker=True,
    )
    _owner(
        home,
        started=NOW - 5 * _HOUR,
        name="hidden-done",
        hidden=True,
        finished=NOW - _HOUR,
    )
    _owner(home, started=NOW - 6 * _HOUR, name="promoted", promoted=True, finished=NOW)
    _owner(
        home,
        started=NOW - 7 * _HOUR,
        name="reconciled",
        finished=NOW - _HOUR,
        tombstoned=True,
    )
    _owner(home, started=NOW - 8 * _HOUR, name="unreadable-meta", finished=NOW)
    # An older unpromoted row is shadowed by the same agent's newer promoted run.
    _owner(home, started=NOW - 10 * _HOUR, name="rerun", finished=NOW - 9 * _HOUR)
    _owner(
        home,
        started=NOW - 9 * _HOUR,
        name="rerun",
        promoted=True,
        finished=NOW - _HOUR,
    )
    unreadable = next(
        path.parent
        for path in home.rglob("agent_meta.json")
        if "unreadable-meta" in path.read_text(encoding="utf-8")
    )
    _build_index(home)
    (unreadable / "agent_meta.json").write_text("{not json", encoding="utf-8")

    walk = _decisions(monkeypatch, home, "walk")

    assert walk == ({"crashed", "hidden-done"}, {"waiter"})
    assert _decisions(monkeypatch, home, "bounded") == walk
    assert _decisions(monkeypatch, home, "sweep") == walk


def test_owners_outside_the_window_wait_for_the_full_history_sweep(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner(home, started=NOW - 2 * _HOUR, name="recent-crash")
    old = NOW - CLAIM_RECENT_WINDOW_SECONDS - 3 * _HOUR
    _owner(home, started=old - _HOUR, name="long-finished", finished=old)
    _owner(home, started=NOW - _HOUR, name="hidden-crash", hidden=True)
    _owner(home, started=old, name="old-promoted", promoted=True, finished=old)
    _owner(home, started=old + 60, name="old-reconciled", finished=old, tombstoned=True)
    _build_index(home)

    walk = _decisions(monkeypatch, home, "walk")
    bounded = _decisions(monkeypatch, home, "bounded")

    assert walk == ({"recent-crash", "long-finished", "hidden-crash"}, set())
    assert bounded == ({"recent-crash"}, set())
    assert _decisions(monkeypatch, home, "sweep") == walk


def _record_queries(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    original = recent.query_agent_artifact_index_payload

    def recording(index_path: Any, projects_root: Any, query: Any, options: Any) -> Any:
        calls.append(query)
        return original(index_path, projects_root, query, options)

    monkeypatch.setattr(recent, "query_agent_artifact_index_payload", recording)
    return calls


def test_bounded_tick_issues_no_full_history_query_and_no_walk(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner(home, started=NOW - _HOUR, name="done", promoted=True, finished=NOW)
    _owner(home, started=NOW - 2 * _HOUR, name="running", promoted=True, alive=True)
    _build_index(home)
    record_claim_full_sweep(time.time())
    queries = _record_queries(monkeypatch)
    monkeypatch.setattr(
        claim_checks,
        "scan_agent_artifacts",
        lambda *_a, **_k: pytest.fail("bounded tick must not walk artifacts"),
    )
    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_a, **_k: pytest.fail("an idle bounded tick opened a bead store"),
    )

    result = claim_checks._run(make_runtime(home))

    assert result.reason == "no_claim_reconciliation_candidates"
    assert queries, "the bounded tick must read the index"
    assert not any(query.include_full_history for query in queries)
    active = [query for query in queries if query.include_active]
    completed = [query for query in queries if not query.include_active]
    assert [query.include_hidden for query in active] == [False]
    assert all(query.include_recent_completed for query in completed)
    assert all(query.include_hidden for query in completed)
    assert all(query.recent_completed_limit for query in completed)


def test_full_history_sweep_cadence_is_persisted(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner(home, started=NOW - _HOUR, name="crashed", promoted=True, finished=NOW)
    _build_index(home)
    queries = _record_queries(monkeypatch)
    projects = home / ".sase" / "projects"

    def full_history_reads(at: float) -> bool:
        queries.clear()
        claim_checks._prepass_claim_artifacts(projects, now=at)
        return any(query.include_full_history for query in queries)

    assert claim_full_sweep_due(NOW)
    assert full_history_reads(NOW)
    assert not claim_full_sweep_due(NOW + 60)
    assert not full_history_reads(NOW + 60)
    assert full_history_reads(NOW + CLAIM_FULL_SWEEP_INTERVAL_SECONDS + 1)
    # A stamp from the future (clock step backwards) must not suppress sweeps.
    record_claim_full_sweep(NOW + 10 * CLAIM_FULL_SWEEP_INTERVAL_SECONDS)
    assert claim_full_sweep_due(NOW)


def test_index_failure_falls_back_to_walk_and_restarts_sweep_interval(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _owner(home, started=NOW - _HOUR, name="crashed")
    _build_index(home)
    record_claim_full_sweep(NOW)

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(recent, "query_agent_artifact_index_payload", broken)
    walked: list[Path] = []
    original = claim_checks._scan_claim_artifacts

    def tracking(root: Path) -> Any:
        walked.append(root)
        return original(root)

    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", tracking)
    later = NOW + 120

    claims = claim_checks._prepass_claim_artifacts(
        home / ".sase" / "projects", now=later
    )

    assert walked
    assert [claim.agent_name for claim in claims] == ["crashed"]
    assert not claim_full_sweep_due(later + 60)
