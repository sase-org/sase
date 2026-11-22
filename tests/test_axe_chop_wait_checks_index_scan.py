"""wait_checks reads waiters from the artifact index between filesystem walks.

Covers the scan-source cadence (first tick and every backstop period walk,
other ticks read the index), the ``SASE_CHOP_SCAN_FULL_WALK`` override, the
index-failure fallback, and the latency guard: a waiter is released on the
first tick after its dependency's done marker lands, through both sources.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import sase.axe.wait_marker_scan as marker_scan
import sase.core.agent_artifact_index_recent as index_recent
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.wait_marker_scan import (
    WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS,
    record_wait_scan_full_walk,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks

FULL_WALK_ENV = "SASE_CHOP_SCAN_FULL_WALK"


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SASE_HOME", raising=False)
    monkeypatch.delenv(FULL_WALK_ENV, raising=False)


def _rebuild_index(tmp_path: Path) -> Path:
    index_path = default_agent_artifact_index_path()
    rebuild_agent_artifact_index(index_path, tmp_path / ".sase" / "projects")
    return index_path


def _tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> str:
    run_wait_checks(tmp_path, monkeypatch)
    summary = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("wait_checks:")
    ]
    assert summary, "wait_checks emitted no summary"
    return summary[-1]


def _forbid_marker_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        marker_scan,
        "iter_agent_artifact_dirs",
        lambda *_a, **_k: pytest.fail("index tick walked artifact dirs"),
    )


def test_first_tick_walks_then_later_ticks_read_the_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_waiting_agent(tmp_path, "foo")
    _rebuild_index(tmp_path)

    first = _tick(tmp_path, monkeypatch, capsys)
    assert "scan_source=walk" in first

    _forbid_marker_walk(monkeypatch)
    second = _tick(tmp_path, monkeypatch, capsys)
    assert "scan_source=index" in second
    assert "waiting=1" in second


def test_backstop_period_walks_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_waiting_agent(tmp_path, "foo")
    _rebuild_index(tmp_path)
    record_wait_scan_full_walk(time.time() - WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS - 1)

    assert "scan_source=walk" in _tick(tmp_path, monkeypatch, capsys)
    assert "scan_source=index" in _tick(tmp_path, monkeypatch, capsys)


def test_full_walk_env_walks_every_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_waiting_agent(tmp_path, "foo")
    _rebuild_index(tmp_path)
    record_wait_scan_full_walk(time.time())
    monkeypatch.setenv(FULL_WALK_ENV, "1")

    assert "scan_source=walk" in _tick(tmp_path, monkeypatch, capsys)
    assert "scan_source=walk" in _tick(tmp_path, monkeypatch, capsys)


def test_missing_index_falls_back_to_walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waiter = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path, "proj", "20260506010101", "foo", done=True, outcome="completed"
    )
    record_wait_scan_full_walk(time.time())

    run_wait_checks(tmp_path, monkeypatch)
    out = capsys.readouterr().out

    assert "fallback=index_unavailable" in out
    assert "scan_source=walk" in out
    assert (waiter / "ready.json").exists()


def _break_index(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("index unreadable")

    monkeypatch.setattr(index_recent, "load_agent_artifact_index_projection", _boom)


@pytest.mark.parametrize("source", ["index", "index_failing", "full_walk_env"])
def test_waiter_releases_on_the_first_tick_after_its_dependency_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source: str,
) -> None:
    """Latency guard: one agent_waits tick after done.json lands, on any source."""
    dependency = make_agent(tmp_path, "proj", "20260506010101", "foo")
    waiter = make_waiting_agent(tmp_path, "foo")
    _rebuild_index(tmp_path)
    if source == "index_failing":
        _break_index(monkeypatch)
    if source == "full_walk_env":
        monkeypatch.setenv(FULL_WALK_ENV, "1")
    # A fresh stamp: only the index or its fallback decides this tick.
    record_wait_scan_full_walk(time.time())
    if source == "index":
        _forbid_marker_walk(monkeypatch)
    expected_source = "index" if source == "index" else "walk"

    parked = _tick(tmp_path, monkeypatch, capsys)
    assert f"scan_source={expected_source}" in parked
    assert "ready_written=0" in parked
    assert not (waiter / "ready.json").exists()

    write_done_marker_and_update_index(
        str(dependency),
        {"patch_name": "foo", "cl_name": "foo", "outcome": "completed"},
    )

    released = _tick(tmp_path, monkeypatch, capsys)
    assert f"scan_source={expected_source}" in released
    assert "ready_written=1" in released
    assert json.loads((waiter / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["foo"],
        "released_by": "wait_checks",
    }


def test_unindexed_waiter_waits_at_most_one_backstop_period(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_agent(
        tmp_path, "proj", "20260506010101", "foo", done=True, outcome="completed"
    )
    _rebuild_index(tmp_path)
    # Written behind the index's back (real writers upsert the row).
    waiter = make_waiting_agent(tmp_path, "foo")
    now = time.time()
    record_wait_scan_full_walk(now)

    unseen = _tick(tmp_path, monkeypatch, capsys)
    assert "scan_source=index" in unseen
    assert "waiting=0" in unseen
    assert not (waiter / "ready.json").exists()

    record_wait_scan_full_walk(now - WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS)

    backstop = _tick(tmp_path, monkeypatch, capsys)
    assert "scan_source=walk" in backstop
    assert (waiter / "ready.json").exists()
