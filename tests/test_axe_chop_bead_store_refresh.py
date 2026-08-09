"""Canonical bead-store refresh chop tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import sase.scripts.sase_chop_bead_store_refresh as store_refresh
from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger


def _runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="bead_store_refresh",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path / "state"),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def _record(
    tmp_path: Path,
    *,
    project_name: str = "proj",
    suffix: str = "waiter",
    wait_for_beads: list[str] | None = None,
    ready: bool = False,
) -> SimpleNamespace:
    artifact_dir = tmp_path / project_name / suffix
    artifact_dir.mkdir(parents=True)
    if ready:
        (artifact_dir / "ready.json").write_text("{}\n", encoding="utf-8")
    return SimpleNamespace(
        project_name=project_name,
        artifact_dir=str(artifact_dir),
        waiting=SimpleNamespace(
            wait_for_beads=(["sase-1"] if wait_for_beads is None else wait_for_beads)
        ),
        agent_meta=SimpleNamespace(pid=123, stopped_at=None),
    )


def _configure_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    records: list[SimpleNamespace],
) -> None:
    monkeypatch.setattr(store_refresh, "bead_refresh_mode", lambda: "background")
    monkeypatch.setattr(store_refresh, "sase_projects_dir", lambda: tmp_path)
    monkeypatch.setattr(
        store_refresh,
        "scan_agent_artifacts",
        lambda _root, _options: SimpleNamespace(records=records),
    )
    monkeypatch.setattr(store_refresh, "is_process_alive", lambda _meta, _path: True)
    monkeypatch.setattr(
        store_refresh,
        "canonical_beads_dir_for_project",
        lambda project: tmp_path / "stores" / project / "beads",
    )


def test_live_bead_wait_refreshes_its_project_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(monkeypatch, tmp_path, [_record(tmp_path)])
    refresh = MagicMock()
    monkeypatch.setattr(store_refresh, "refresh_bead_store", refresh)

    result = store_refresh._run(_runtime(tmp_path))

    refresh.assert_called_once_with(
        tmp_path / "stores/proj/beads",
        lock_timeout=store_refresh._refresh_lock_timeout(1),
    )
    assert result.status == "ok"
    assert result.counters == {
        "projects_waiting": 1,
        "stores_refreshed": 1,
        "stores_failed": 0,
        "stores_backed_off": 0,
        "stores_deferred": 0,
    }


def test_multiple_waiters_in_one_project_are_deduplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(
        monkeypatch,
        tmp_path,
        [
            _record(tmp_path, suffix="one"),
            _record(tmp_path, suffix="two"),
        ],
    )
    refresh = MagicMock()
    monkeypatch.setattr(store_refresh, "refresh_bead_store", refresh)

    result = store_refresh._run(_runtime(tmp_path))

    refresh.assert_called_once()
    assert result.counters["projects_waiting"] == 1


def test_ready_bead_wait_does_not_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(monkeypatch, tmp_path, [_record(tmp_path, ready=True)])
    refresh = MagicMock()
    monkeypatch.setattr(store_refresh, "refresh_bead_store", refresh)

    result = store_refresh._run(_runtime(tmp_path))

    refresh.assert_not_called()
    assert result.reason == "no_bead_waits"


def test_non_bead_wait_does_not_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(
        monkeypatch,
        tmp_path,
        [_record(tmp_path, wait_for_beads=[])],
    )
    refresh = MagicMock()
    monkeypatch.setattr(store_refresh, "refresh_bead_store", refresh)

    result = store_refresh._run(_runtime(tmp_path))

    refresh.assert_not_called()
    assert result.reason == "no_bead_waits"


def test_dead_waiter_is_dropped_but_uncertain_liveness_fails_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dead = _record(tmp_path, project_name="dead")
    uncertain = _record(tmp_path, project_name="uncertain")
    _configure_scan(monkeypatch, tmp_path, [dead, uncertain])

    def liveness(_meta: dict[str, object], artifact_dir: Path) -> bool:
        if artifact_dir == Path(dead.artifact_dir):
            return False
        raise PermissionError("liveness unavailable")

    monkeypatch.setattr(store_refresh, "is_process_alive", liveness)
    refreshed: list[Path] = []
    monkeypatch.setattr(
        store_refresh,
        "refresh_bead_store",
        lambda beads_dir, **_kwargs: refreshed.append(beads_dir),
    )

    result = store_refresh._run(_runtime(tmp_path))

    assert refreshed == [tmp_path / "stores/uncertain/beads"]
    assert result.counters["projects_waiting"] == 1


def test_off_mode_short_circuits_before_scanning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store_refresh, "bead_refresh_mode", lambda: "off")
    monkeypatch.setattr(
        store_refresh,
        "scan_agent_artifacts",
        lambda *_args: pytest.fail("disabled refresh scanned artifacts"),
    )

    result = store_refresh._run(_runtime(tmp_path))

    assert result.reason == "bead_refresh_disabled"
    assert result.counters["projects_waiting"] == 0


def test_refresh_failure_backs_off_then_success_clears_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(monkeypatch, tmp_path, [_record(tmp_path)])
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    current_time = [now]
    monkeypatch.setattr(store_refresh, "_utc_now", lambda: current_time[0])
    refresh = MagicMock(side_effect=[RuntimeError("remote down"), None])
    monkeypatch.setattr(store_refresh, "refresh_bead_store", refresh)
    runtime = _runtime(tmp_path)

    failed = store_refresh._run(runtime)
    backed_off = store_refresh._run(runtime)
    current_time[0] = now + timedelta(minutes=2)
    recovered = store_refresh._run(runtime)

    assert failed.status == "no_op"
    assert failed.reason == "refresh_failed"
    assert failed.counters["stores_failed"] == 1
    assert backed_off.reason == "all_backed_off"
    assert backed_off.counters["stores_backed_off"] == 1
    assert recovered.status == "ok"
    assert recovered.counters["stores_refreshed"] == 1
    assert refresh.call_count == 2
    state_path = Path(runtime.context.state_dir) / store_refresh._BACKOFF_STATE_FILENAME
    assert json.loads(state_path.read_text(encoding="utf-8")) == {}


def test_backoff_state_is_pruned_for_projects_without_waiters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(monkeypatch, tmp_path, [_record(tmp_path, project_name="alive")])
    runtime = _runtime(tmp_path)
    state_path = Path(runtime.context.state_dir) / store_refresh._BACKOFF_STATE_FILENAME
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "gone": {
                    "failures": 3,
                    "next_attempt_at": "2099-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(store_refresh, "refresh_bead_store", MagicMock())

    result = store_refresh._run(runtime)

    assert result.counters["stores_refreshed"] == 1
    assert json.loads(state_path.read_text(encoding="utf-8")) == {}


def test_backoff_state_is_pruned_when_no_project_has_waiters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(monkeypatch, tmp_path, [])
    runtime = _runtime(tmp_path)
    state_path = Path(runtime.context.state_dir) / store_refresh._BACKOFF_STATE_FILENAME
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "gone": {
                    "failures": 3,
                    "next_attempt_at": "2099-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    result = store_refresh._run(runtime)

    assert result.reason == "no_bead_waits"
    assert json.loads(state_path.read_text(encoding="utf-8")) == {}


def test_lock_wait_is_split_across_waiting_projects_above_a_floor() -> None:
    assert (
        store_refresh._refresh_lock_timeout(1)
        == store_refresh._LOCK_WAIT_BUDGET_SECONDS
    )
    assert store_refresh._refresh_lock_timeout(1) < store_refresh._CHOP_TIMEOUT_SECONDS
    # Every project's share stays at or above the floor, and the whole pass
    # still fits inside the chop's own timeout.
    for count in (2, 3, 6, 12, 50):
        share = store_refresh._refresh_lock_timeout(count)
        assert share >= store_refresh._MIN_LOCK_WAIT_SECONDS
        assert share <= store_refresh._LOCK_WAIT_BUDGET_SECONDS


def test_contended_refresh_declines_and_records_backoff_within_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(monkeypatch, tmp_path, [_record(tmp_path)])
    timeouts: list[float | None] = []

    def contended(_beads_dir: Path, *, lock_timeout: float | None = None) -> None:
        timeouts.append(lock_timeout)
        raise RuntimeError("could not acquire the bead-store refresh lock")

    monkeypatch.setattr(store_refresh, "refresh_bead_store", contended)
    runtime = _runtime(tmp_path)

    result = store_refresh._run(runtime)

    assert timeouts == [store_refresh._refresh_lock_timeout(1)]
    assert timeouts[0] < store_refresh._CHOP_TIMEOUT_SECONDS
    assert result.reason == "refresh_failed"
    state_path = Path(runtime.context.state_dir) / store_refresh._BACKOFF_STATE_FILENAME
    assert json.loads(state_path.read_text(encoding="utf-8"))["proj"]["failures"] == 1


def test_backoff_survives_a_kill_during_the_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(monkeypatch, tmp_path, [_record(tmp_path)])

    def killed(_beads_dir: Path, **_kwargs: object) -> None:
        # A chop-timeout SIGKILL gives the handler no chance to record state.
        raise KeyboardInterrupt

    monkeypatch.setattr(store_refresh, "refresh_bead_store", killed)
    runtime = _runtime(tmp_path)

    with pytest.raises(KeyboardInterrupt):
        store_refresh._run(runtime)

    state_path = Path(runtime.context.state_dir) / store_refresh._BACKOFF_STATE_FILENAME
    assert json.loads(state_path.read_text(encoding="utf-8"))["proj"]["failures"] == 1

    # The next run sees the recorded backoff instead of re-attacking the lock.
    monkeypatch.setattr(
        store_refresh,
        "refresh_bead_store",
        lambda *_args, **_kwargs: pytest.fail("backed-off project was re-attempted"),
    )
    backed_off = store_refresh._run(runtime)

    assert backed_off.reason == "all_backed_off"
    assert backed_off.counters["stores_backed_off"] == 1


def test_exhausted_work_budget_defers_remaining_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(
        monkeypatch,
        tmp_path,
        [_record(tmp_path, project_name="one"), _record(tmp_path, project_name="two")],
    )
    clock = iter([0.0, 0.0, store_refresh._WORK_BUDGET_SECONDS + 1.0])
    monkeypatch.setattr(
        store_refresh,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock)),
    )
    refresh = MagicMock()
    monkeypatch.setattr(store_refresh, "refresh_bead_store", refresh)

    result = store_refresh._run(_runtime(tmp_path))

    assert refresh.call_count == 1
    assert result.counters["stores_refreshed"] == 1
    assert result.counters["stores_deferred"] == 1


def test_corrupt_backoff_state_is_treated_as_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_scan(monkeypatch, tmp_path, [_record(tmp_path)])
    runtime = _runtime(tmp_path)
    state_path = Path(runtime.context.state_dir) / store_refresh._BACKOFF_STATE_FILENAME
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{not-json", encoding="utf-8")
    refresh = MagicMock()
    monkeypatch.setattr(store_refresh, "refresh_bead_store", refresh)

    result = store_refresh._run(runtime)

    refresh.assert_called_once()
    assert result.counters["stores_refreshed"] == 1
