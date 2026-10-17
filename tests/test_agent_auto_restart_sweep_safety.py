"""Tests for the sweep-safety phase: healer touches only skew-shaped rows.

Covers the phase contract: candidate enumeration shared by ``run -p`` and
the scheduler job, the ``heal_one`` non-candidate pre-check, doorbell
handling, the silenced-only disabled path, ``write_recovery`` safety, the
trip-once storm breaker, and cheap idle ticks.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.auto_restart.healer import HealerTarget, heal_one
from sase.agent.auto_restart.healer_targets import is_healer_candidate
from sase.axe import runner_auto_restart_doorbell as doorbell_mod

PROVIDER_429 = (
    "ProviderError: 429 rate limited — quota exhausted for model; retry after 60s"
)
SKEW_ERROR = "ImportError: cannot import name 'auto_launch_prefix'"


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate all state-dir writes (ledger, doorbells, projects, storm)."""
    home = tmp_path / "home"
    home.mkdir()
    import sase.core.paths as paths

    monkeypatch.setattr(paths, "sase_home", lambda: home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("SASE_HOME", str(home))
    from sase.agent.auto_restart import ledger as ledger_mod

    ledger_mod._clear_ledger_records_cache()
    return home


@pytest.fixture
def quiet_notifications(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Capture healer notifications without touching the real store."""
    import sase.agent.auto_restart.notify as notify

    calls: dict[str, list] = {"relaunch": [], "escalation": [], "resurface": []}
    monkeypatch.setattr(
        notify, "publish_relaunch", lambda **kw: calls["relaunch"].append(kw)
    )
    monkeypatch.setattr(
        notify, "publish_escalation", lambda **kw: calls["escalation"].append(kw)
    )
    monkeypatch.setattr(
        notify, "resurface_failure", lambda **kw: calls["resurface"].append(kw)
    )
    return calls


def _projects_row(
    home: Path, stamp: str, done: dict[str, Any], name: str = "safety-worker"
) -> Path:
    """Write one failed row under the isolated projects tree."""
    artifacts = home / "projects" / "sase" / "artifacts" / "ace-run" / stamp
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "done.json").write_text(json.dumps(done), encoding="utf-8")
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": name}), encoding="utf-8"
    )
    return artifacts


def _target(artifacts: Path, name: str = "safety-worker") -> HealerTarget:
    return HealerTarget(artifacts_dir=artifacts, project="sase", agent_name=name)


def _decline_verdict() -> SimpleNamespace:
    return SimpleNamespace(
        mode="decline",
        reason="no_update_witness",
        reason_text="not skew-shaped",
        episode_id="sase@test",
    )


# --- candidate rule ----------------------------------------------------------


def test_candidate_rule_matrix(tmp_home: Path) -> None:
    _ = tmp_home
    now = time.time()
    base = {"outcome": "failed"}
    row = Path("/tmp/row/20261009T120000")
    assert is_healer_candidate(
        artifacts_dir=row, done=dict(base), has_doorbell=True, now=now
    )
    assert is_healer_candidate(
        artifacts_dir=row,
        done={**base, "recovery": {"state": "pending"}},
        now=now,
    )
    assert is_healer_candidate(
        artifacts_dir=row,
        done={**base, "failure_facts": {"skew_suspect": True}},
        now=now,
    )
    # Non-skew text with facts present but not suspect: never a candidate.
    assert not is_healer_candidate(
        artifacts_dir=row,
        done={**base, "error": PROVIDER_429, "failure_facts": {"skew_suspect": False}},
        now=now,
    )
    # Non-failed rows are never candidates, even with a doorbell.
    assert not is_healer_candidate(
        artifacts_dir=row,
        done={"outcome": "completed"},
        has_doorbell=True,
        now=now,
    )


def test_recent_non_skew_row_untouched(
    tmp_home: Path, quiet_notifications: dict[str, list]
) -> None:
    """A recent provider-429 row: no ledger, no write, no ping via both paths."""
    import datetime

    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod
    from sase.agent.auto_restart.healer_targets import resolve_pending_targets
    from sase.core.time import get_timezone

    stamp = datetime.datetime.now(get_timezone()).strftime("%Y%m%d%H%M%S")
    row = _projects_row(
        tmp_home,
        stamp,
        {"outcome": "failed", "error": PROVIDER_429},
    )
    before = (row / "done.json").read_text(encoding="utf-8")
    now = time.time()
    assert resolve_pending_targets(now=now) == []
    outcome = heal_one(_target(row), now=now)
    assert outcome.action == "skipped"
    assert outcome.reason == "not_update_skew"
    assert ledger_mod.iter_ledger_records() == []
    assert (row / "done.json").read_text(encoding="utf-8") == before
    assert quiet_notifications == {"relaunch": [], "escalation": [], "resurface": []}
    with (
        patch(
            "sase.agent.auto_restart.gate.auto_restart_automatic_enabled",
            return_value=True,
        ),
        patch.object(sweep_mod, "_proc_already_queued", return_value=True),
        patch.object(sweep_mod, "_submit_healer_proc") as submit,
    ):
        tick = sweep_mod.run_job_tick(now=now)
    assert tick.action == "idle"
    assert ledger_mod.iter_ledger_records() == []
    assert (row / "done.json").read_text(encoding="utf-8") == before
    assert quiet_notifications == {"relaunch": [], "escalation": [], "resurface": []}
    submit.assert_not_called()


def test_non_skew_row_and_dismissed_bundle_untouched(
    tmp_home: Path, quiet_notifications: dict[str, list]
) -> None:
    """A provider-429 row and a dismissed bundle: no ledger, no write, no ping."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart.healer_targets import resolve_pending_targets

    row = _projects_row(
        tmp_home,
        "20261009T120000",
        {"outcome": "failed", "error": PROVIDER_429},
    )
    before = (row / "done.json").read_text(encoding="utf-8")
    # A dismissed bundle for an already-wiped row.
    bundles = tmp_home / "dismissed_bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    (bundles / "20261009120000_safety-old.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "error_message": SKEW_ERROR,
                "artifacts_dir": str(tmp_home / "projects" / "sase" / "wiped-row"),
                "agent_name": "safety-old",
                "cl_name": "sase",
            }
        ),
        encoding="utf-8",
    )

    assert resolve_pending_targets(now=time.time()) == []
    outcome = heal_one(_target(row), now=time.time())
    assert outcome.action == "skipped"
    assert outcome.reason == "not_update_skew"
    assert ledger_mod.iter_ledger_records() == []
    assert (row / "done.json").read_text(encoding="utf-8") == before
    assert quiet_notifications == {"relaunch": [], "escalation": [], "resurface": []}


def test_job_tick_ignores_non_skew_and_bundles(
    tmp_home: Path, quiet_notifications: dict[str, list]
) -> None:
    """run_job_tick stays idle over non-candidates and sends nothing."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod

    _projects_row(
        tmp_home, "20261009T120000", {"outcome": "failed", "error": PROVIDER_429}
    )
    submissions: list[int] = []
    with (
        patch(
            "sase.agent.auto_restart.gate.auto_restart_automatic_enabled",
            return_value=True,
        ),
        patch("sase.procs.store.read_procs", return_value=[]),
        patch.object(
            sweep_mod,
            "_submit_healer_proc",
            lambda *, count: submissions.append(count) or True,
        ),
    ):
        tick = sweep_mod.run_job_tick(now=time.time())
    assert tick.action == "idle", tick
    assert submissions == []
    assert ledger_mod.iter_ledger_records() == []
    assert quiet_notifications == {"relaunch": [], "escalation": [], "resurface": []}


def test_stale_legacy_row_is_ignored(tmp_home: Path) -> None:
    """A skew-shaped legacy row older than max_defer_seconds is ignored."""
    from sase.agent.auto_restart.healer_targets import resolve_pending_targets

    row = _projects_row(
        tmp_home,
        "20200101T000000",
        {"outcome": "failed", "error": SKEW_ERROR},
    )
    assert resolve_pending_targets(now=time.time()) == []
    outcome = heal_one(_target(row), now=time.time())
    assert outcome.action == "skipped"
    assert outcome.reason == "not_update_skew"


def test_recent_legacy_skew_row_is_candidate(tmp_home: Path) -> None:
    """A recent skew-shaped legacy row without markers is still a candidate."""
    import datetime

    from sase.core.time import get_timezone

    stamp = datetime.datetime.now(get_timezone()).strftime("%Y%m%dT%H%M%S")
    row = _projects_row(tmp_home, stamp, {"outcome": "failed", "error": SKEW_ERROR})
    assert is_healer_candidate(
        artifacts_dir=row,
        done=json.loads((row / "done.json").read_text(encoding="utf-8")),
        now=time.time(),
    )


# --- doorbells -----------------------------------------------------------------


def test_orphan_ledger_records_resolve_and_next_tick_idle(
    tmp_home: Path, quiet_notifications: dict[str, list]
) -> None:
    """Ledger-only orphans (missing done.json) resolve; next tick is idle."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod
    from sase.agent.auto_restart.healer_targets import resolve_pending_targets

    missing = str(tmp_home / "projects" / "sase" / "artifacts" / "gone-row")
    stored = ledger_mod.claim_ledger_record(
        key="sase__gone-row",
        lineage_root="gone-row",
        agent_name="orphan-worker",
        project="sase",
        failed_artifacts_dir=missing,
    )
    assert stored is not None
    stored = ledger_mod.advance_ledger_record(stored, "defer", note="wait")
    dead = ledger_mod.StoredLedgerRecord(
        record=stored.record,
        extra={**stored.extra, "python_claimer_pid": 2**30},
    )
    ledger_mod.store_ledger_record(dead)
    targets = resolve_pending_targets(now=time.time())
    assert any(str(t.artifacts_dir) == missing for t in targets)
    for target in targets:
        if str(target.artifacts_dir) == missing:
            outcome = heal_one(target, now=time.time())
            assert outcome.action == "declined"
            assert outcome.reason == "row_gone"
    assert quiet_notifications == {"relaunch": [], "escalation": [], "resurface": []}
    work = sweep_mod._collect_job_work(now=time.time())
    assert work.actionable is False


def test_handled_doorbell_deleted_and_next_tick_idle(
    tmp_home: Path, quiet_notifications: dict[str, list]
) -> None:
    """One healer pass over a doorbell deletes it; the next tick is idle."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod

    row = _projects_row(
        tmp_home,
        "20261009T120000",
        {
            "outcome": "failed",
            "error": SKEW_ERROR,
            "failure_facts": {"skew_suspect": True},
        },
    )
    doorbell_path = doorbell_mod.drop_doorbell(
        artifacts_dir=str(row), project="sase", agent_name="safety-worker"
    )
    assert doorbell_path is not None and Path(doorbell_path).is_file()

    outcome = heal_one(
        _target(row),
        classify=lambda assembled: _decline_verdict(),
        now=time.time(),
    )
    assert outcome.action == "declined"
    assert not Path(doorbell_path).exists()
    assert ledger_mod.list_doorbells() == []

    work = sweep_mod._collect_job_work(now=time.time())
    assert work.actionable is False


# --- disabled path -------------------------------------------------------------


def test_disabled_path_resurfaces_silenced_once_and_ignores_others(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silenced rows resurface exactly once; non-silenced rows are untouched."""
    import datetime

    import sase.agent.auto_restart.notify as notify
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod
    from sase.core.time import get_timezone

    now = time.time()
    tz = get_timezone()
    silenced_stamp = datetime.datetime.fromtimestamp(now - 600, tz=tz).strftime(
        "%Y%m%dT%H%M%S"
    )
    plain_stamp = datetime.datetime.fromtimestamp(now - 60, tz=tz).strftime(
        "%Y%m%dT%H%M%S"
    )
    silenced = _projects_row(
        tmp_home,
        silenced_stamp,
        {
            "outcome": "failed",
            "error": SKEW_ERROR,
            "recovery": {
                "state": "pending",
                "reason": None,
                "reason_text": "recovery pending",
                "requested_at": "2026-10-09T12:00:00+00:00",
                "updated_at": "2026-10-09T12:00:00+00:00",
                "episode_id": None,
            },
        },
        name="silenced-worker",
    )
    plain = _projects_row(
        tmp_home,
        plain_stamp,
        {"outcome": "failed", "error": PROVIDER_429},
        name="plain-worker",
    )
    plain_before = (plain / "done.json").read_text(encoding="utf-8")

    resurfaced: list[dict[str, Any]] = []
    monkeypatch.setattr(
        notify, "resurface_failure", lambda **kw: resurfaced.append(kw) or None
    )
    monkeypatch.setattr(
        "sase.agent.auto_restart.gate.auto_restart_automatic_enabled",
        lambda: False,
    )
    counts = []
    base = time.time()
    for step in range(3):
        tick = sweep_mod.run_job_tick(now=base + step)
        assert tick.action == "disabled", tick
        counts.append(tick.resurfaced)
    assert counts == [1, 0, 0]
    assert len(resurfaced) == 1
    done = json.loads((silenced / "done.json").read_text(encoding="utf-8"))
    assert done["recovery"]["state"] == "declined"
    assert (plain / "done.json").read_text(encoding="utf-8") == plain_before
    assert ledger_mod.iter_ledger_records() == []


# --- write_recovery safety -------------------------------------------------------


def test_write_recovery_creates_nothing_and_dry_run_writes_nothing(
    tmp_home: Path,
) -> None:
    from sase.agent.auto_restart.healer import write_recovery

    missing = tmp_home / "projects" / "sase" / "artifacts" / "ace-run" / "gone-row"
    write_recovery(_target(missing), "declined", "nope", now=time.time())
    assert not missing.exists()

    row = _projects_row(
        tmp_home, "20261009T120000", {"outcome": "failed", "error": PROVIDER_429}
    )
    before = (row / "done.json").read_text(encoding="utf-8")
    write_recovery(_target(row), "declined", "dry", now=time.time(), dry_run=True)
    assert (row / "done.json").read_text(encoding="utf-8") == before


# --- storm breaker ---------------------------------------------------------------


def test_storm_sends_exactly_one_escalation(
    tmp_home: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three over-limit targets: one storm escalation, three quiet declines."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import storm as storm_mod

    _ = tmp_home
    episode = f"sase@test-{uuid.uuid4().hex[:6]}"
    for index in range(3):
        stored = ledger_mod.claim_ledger_record(
            key=f"safety__storm-{index}-{uuid.uuid4().hex[:6]}",
            lineage_root=f"storm-lineage-{index}",
        )
        assert stored is not None
        stored = ledger_mod.advance_ledger_record(stored, "begin_launch")
        stored = ledger_mod.advance_ledger_record(stored, "launched")
        import dataclasses

        ledger_mod.store_ledger_record(
            ledger_mod.StoredLedgerRecord(
                record=dataclasses.replace(stored.record, episode_id=episode),
                extra=dict(stored.extra),
            )
        )
    monkeypatch.setattr(
        "sase.config._settings_system.get_agent_auto_restart_storm_max_per_episode",
        lambda: 1,
    )
    monkeypatch.setattr(
        "sase.config._settings_system.get_agent_auto_restart_storm_max_per_30m",
        lambda: 1000,
    )

    def _relaunch() -> SimpleNamespace:
        return SimpleNamespace(
            mode="relaunch",
            reason="torn_python",
            reason_text="skew",
            episode_id=episode,
        )

    outcomes = []
    for index in range(3):
        row = _projects_row(
            tmp_home,
            f"20261009T12{index:02d}00",
            {
                "outcome": "failed",
                "error": SKEW_ERROR,
                "failure_facts": {"skew_suspect": True},
            },
            name=f"storm-worker-{index}",
        )
        outcomes.append(
            heal_one(
                _target(row, name=f"storm-worker-{index}"),
                classify=lambda assembled: _relaunch(),
                check_quiescence=lambda: SimpleNamespace(ok=True, reason="quiet"),
                run_probe=lambda modules, binding_checks=None: SimpleNamespace(
                    ok=True, failures=(), detail="clean"
                ),
                now=time.time(),
            )
        )
    assert [o.action for o in outcomes] == ["declined"] * 3
    assert [o.reason for o in outcomes] == ["paused"] * 3
    assert len(quiet_notifications["escalation"]) == 1
    assert quiet_notifications["escalation"][0]["kind"] == "storm"
    assert quiet_notifications["resurface"] == []
    paused, _ = storm_mod.is_paused()
    assert paused


# --- idle cost ---------------------------------------------------------------------


def test_idle_tick_skips_ledger_parse(tmp_home: Path) -> None:
    """An unchanged ledger costs no re-parse on the next idle tick."""
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import sweep as sweep_mod

    _ = tmp_home
    first = sweep_mod._collect_job_work(now=1000.0)
    assert first.full_scan is True
    assert first.actionable is False

    calls: list[str] = []
    real = ledger_mod.iter_ledger_records
    import unittest.mock as mock

    with mock.patch.object(
        ledger_mod, "iter_ledger_records", lambda: calls.append("parse") or real()
    ):
        second = sweep_mod._collect_job_work(now=1001.0)
    assert calls == []
    assert second.full_scan is False
    assert second.actionable is False

    stored = ledger_mod.claim_ledger_record(
        key=f"safety__idle-{uuid.uuid4().hex[:6]}", lineage_root="idle-lineage"
    )
    assert stored is not None
    with mock.patch.object(
        ledger_mod, "iter_ledger_records", lambda: calls.append("parse") or real()
    ):
        sweep_mod._collect_job_work(now=1002.0)
    assert calls == ["parse"]


def test_cached_ledger_listing_sees_record_rewrites(tmp_home: Path) -> None:
    """Rewriting an existing record invalidates the cached listing.

    Directory mtime can freeze across rapid rewrites (no new dentries), so
    the writers invalidate the cache directly; otherwise a collect right
    after a decline still reports the pre-decline state.
    """
    from sase.agent.auto_restart import ledger as ledger_mod

    _ = tmp_home
    stored = ledger_mod.claim_ledger_record(
        key=f"safety__rewrite-{uuid.uuid4().hex[:6]}",
        lineage_root="rewrite-lineage",
    )
    assert stored is not None
    assert [
        (entry.record.key, entry.record.state)
        for entry in ledger_mod.iter_ledger_records_cached()
        if entry.record.key == stored.record.key
    ] == [(stored.record.key, "claimed")]
    stored = ledger_mod.advance_ledger_record(stored, "defer", note="wait")
    assert [
        (entry.record.key, entry.record.state)
        for entry in ledger_mod.iter_ledger_records_cached()
        if entry.record.key == stored.record.key
    ] == [(stored.record.key, "deferred")]


def test_idle_job_tick_bounds_filesystem_calls(tmp_home: Path) -> None:
    """An idle run_job_tick (not a full sweep) stays at a handful of stats."""
    import os as _os
    import unittest.mock as _mock

    from sase.agent.auto_restart import sweep as sweep_mod

    _ = tmp_home
    sweep_mod._collect_job_work(now=1000.0)
    counts = {"stat": 0, "open": 0, "scandir": 0}
    real_stat = _os.stat
    real_open = open
    real_scandir = _os.scandir
    import builtins as _builtins

    def _stat(*args: Any, **kwargs: Any) -> Any:
        counts["stat"] += 1
        return real_stat(*args, **kwargs)

    def _open(*args: Any, **kwargs: Any) -> Any:
        counts["open"] += 1
        return real_open(*args, **kwargs)

    def _scandir(*args: Any, **kwargs: Any) -> Any:
        counts["scandir"] += 1
        return real_scandir(*args, **kwargs)

    with (
        patch(
            "sase.agent.auto_restart.gate.auto_restart_automatic_enabled",
            return_value=True,
        ),
        patch.object(sweep_mod, "_proc_already_queued", return_value=True),
        _mock.patch.object(_os, "stat", _stat),
        _mock.patch.object(_builtins, "open", _open),
        _mock.patch.object(_os, "scandir", _scandir),
    ):
        tick = sweep_mod.run_job_tick(now=1001.0)
    assert tick.action == "idle"
    assert counts["stat"] + counts["open"] + counts["scandir"] <= 60
