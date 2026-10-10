"""Tests for the update-skew healer phase (ledger claim, skips, relaunch)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.auto_restart import healer
from sase.agent.auto_restart._healer_common import apply_skip_rules
from sase.agent.auto_restart.healer import (
    HealerTarget,
    heal_one,
)
from sase.agent.auto_restart.probe import run_probe
from sase.agent.auto_restart.quiescence import check_quiescence


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate all state-dir writes (ledger, evidence, storm state)."""
    home = tmp_path / "home"
    home.mkdir()
    import sase.core.paths as paths

    monkeypatch.setattr(paths, "sase_home", lambda: home)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def failed_row(tmp_path: Path) -> Path:
    """One minimal failed agent row the healer may attempt."""
    artifacts = tmp_path / "artifacts" / "ace-run" / "20261009T120000"
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps(
            {
                "outcome": "failed",
                "error": "ImportError: cannot import name 'auto_launch_prefix'",
                "finished_at": 1720000000.0,
                # Skew-suspect so the row passes the healer candidate
                # pre-check (sweep-safety); the stale timestamp proves the
                # suspect path does not depend on legacy recency.
                "failure_facts": {
                    "lifecycle_phase": "waiting",
                    "skew_suspect": True,
                },
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": f"healer-test-{uuid.uuid4().hex[:8]}"}),
        encoding="utf-8",
    )
    (artifacts / "error_report.md").write_text("# boom\n", encoding="utf-8")
    return artifacts


def _target(artifacts: Path) -> HealerTarget:
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    return HealerTarget(
        artifacts_dir=artifacts, project="sase", agent_name=str(meta["name"])
    )


def _relaunch_verdict() -> SimpleNamespace:
    return SimpleNamespace(
        tier="1",
        family="torn_python_import",
        signature="ImportError: cannot import name 'auto_launch_prefix'",
        origin_module="sase.monitor.continuation_delivery",
        missing_symbol="auto_launch_prefix",
        phase_class="pre_provider",
        mode="relaunch",
        reason="torn_python",
        reason_text="in-memory code asked the new tree for a removed symbol",
        witnesses_fired=("W1", "W4"),
        episode_id="sase@9fd8a08",
    )


def _assembled() -> SimpleNamespace:
    return SimpleNamespace(
        facts=SimpleNamespace(frames=[]),
        witnesses=SimpleNamespace(probe=None, file_proof=None),
        context=SimpleNamespace(),
    )


def _ok_quiescence() -> SimpleNamespace:
    return SimpleNamespace(ok=True, reason="quiet", quiet_seconds=60.0)


def _ok_probe_result() -> SimpleNamespace:
    return SimpleNamespace(ok=True, failures=(), detail="clean")


def _plan_double(target: HealerTarget) -> SimpleNamespace:
    return SimpleNamespace(
        rewritten_prompt="relaunch prompt",
        artifacts_dir=target.artifacts_dir,
        force_reuse_plan=SimpleNamespace(segment_envs=[None]),
        preview=SimpleNamespace(is_live=False),
        wipe_preview=SimpleNamespace(artifact_dirs=[str(target.artifacts_dir)]),
    )


def _execute_ok(new_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(status="ok", launched_artifacts_dir=str(new_dir), error=None)


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


# Skip rules: user intent wins.
def test_skip_already_restarted(failed_row: Path) -> None:
    meta_path = failed_row / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["auto_restart"] = {"ledger_key": "sase__abc"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    done = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    decision = apply_skip_rules(_target(failed_row), done=done, meta=meta)
    assert decision.skip
    assert decision.decline_reason == "already_restarted"


def test_skip_killed_outcome(failed_row: Path) -> None:
    done = {"outcome": "killed", "kill_source": "user"}
    decision = apply_skip_rules(_target(failed_row), done=done, meta={})
    assert decision.skip
    assert decision.decline_reason == "killed"
    assert not decision.loud


def test_skip_non_failed_row(failed_row: Path) -> None:
    done = {"outcome": "done"}
    decision = apply_skip_rules(_target(failed_row), done=done, meta={})
    assert decision.skip
    assert decision.decline_reason == "no_longer_failed"


def test_skip_remote_row(failed_row: Path) -> None:
    done = {"outcome": "failed", "is_remote": True}
    decision = apply_skip_rules(_target(failed_row), done=done, meta={})
    assert decision.skip
    assert decision.decline_reason == "remote"


def test_no_skip_for_plain_failed_row(failed_row: Path) -> None:
    done = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    decision = apply_skip_rules(_target(failed_row), done=done, meta={})
    assert not decision.skip


# Ledger claim liveness.
def test_claimer_liveness_dead_pid_and_self(tmp_home: Path) -> None:
    from sase.agent.auto_restart import ledger as ledger_mod

    _ = tmp_home
    stored = ledger_mod.claim_ledger_record(
        key=f"test__live-{uuid.uuid4().hex[:8]}", lineage_root="live"
    )
    assert stored is not None
    assert ledger_mod.claimer_is_live(stored) is True
    dead = ledger_mod.StoredLedgerRecord(
        record=stored.record,
        extra={**stored.extra, "python_claimer_pid": 2**30},
    )
    assert ledger_mod.claimer_is_live(dead) is False


# Storm breaker.
def test_storm_breaker_trips_and_resume_rearms(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import storm as storm_mod

    _ = tmp_home
    records = []
    for index in range(3):
        stored = ledger_mod.claim_ledger_record(
            key=f"test__lineage-{index}-{uuid.uuid4().hex[:6]}",
            lineage_root=f"lineage-{index}",
        )
        assert stored is not None
        stored = ledger_mod.advance_ledger_record(stored, "begin_launch")
        stored = ledger_mod.advance_ledger_record(stored, "launched")
        import dataclasses

        stored = ledger_mod.store_ledger_record(
            ledger_mod.StoredLedgerRecord(
                record=dataclasses.replace(stored.record, episode_id="sase@abc"),
                extra=dict(stored.extra),
            )
        )
        records.append(stored)
    decision = storm_mod.storm_check(
        records, episode_id="sase@abc", max_per_episode=2, max_per_30m=20
    )
    assert not decision.allowed
    assert "sase@abc" in decision.reason
    storm_mod.trip_pause(reason=decision.reason, episode="sase@abc")
    paused, state = storm_mod.is_paused()
    assert paused
    assert state["paused_episode"] == "sase@abc"
    storm_mod.clear_pause()
    paused_after, _ = storm_mod.is_paused()
    assert paused_after is False


def test_storm_window_counts_only_launches(tmp_home: Path) -> None:
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart import storm as storm_mod

    _ = tmp_home
    claimed = ledger_mod.claim_ledger_record(
        key=f"test__claimed-{uuid.uuid4().hex[:8]}", lineage_root="claimed-only"
    )
    assert claimed is not None
    decision = storm_mod.storm_check(
        [claimed], episode_id="sase@abc", max_per_episode=1, max_per_30m=1
    )
    assert decision.allowed


# Probe and quiescence smoke.
def test_probe_imports_stdlib_cleanly() -> None:
    result = run_probe(["json", "os"])
    assert result.ok, result.detail


def test_probe_reports_missing_module() -> None:
    result = run_probe(["sase_no_such_module_xyz"])
    assert not result.ok
    assert result.failures


def test_quiescence_returns_a_reason() -> None:
    result = check_quiescence(quiescence_seconds=0)
    assert isinstance(result.ok, bool)
    assert result.reason


# Gate: the config kill switch alone decides (the beta flag is retired).
def test_gate_off_when_config_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.config._settings_system as settings
    from sase.agent.auto_restart import gate

    monkeypatch.setattr(settings, "get_agent_auto_restart_enabled", lambda: False)
    assert gate.auto_restart_automatic_enabled() is False


def test_gate_on_when_config_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.config._settings_system as settings
    from sase.agent.auto_restart import gate

    monkeypatch.setattr(settings, "get_agent_auto_restart_enabled", lambda: True)
    assert gate.auto_restart_automatic_enabled() is True


# Healer happy path with injected fakes (ledger + evidence are real).
def test_healer_relaunches_once_then_declines(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    target = _target(failed_row)
    launched: list[str] = []

    def fake_execute(plan: Any, evidence_files: dict[str, Any]) -> SimpleNamespace:
        assert "verdict.json" in evidence_files
        assert "error_report.md" in evidence_files
        new_dir = failed_row.parent / "20261009T120100"
        new_dir.mkdir(parents=True, exist_ok=True)
        launched.append(str(new_dir))
        return _execute_ok(new_dir)

    outcome = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=_ok_quiescence,
        run_probe=lambda modules, binding_checks=None: _ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=fake_execute,
    )
    assert outcome.action == "relaunched", outcome.reason_text
    assert outcome.launched_artifacts_dir == launched[0]
    assert outcome.evidence_dir is not None
    assert Path(outcome.evidence_dir, "verdict.json").is_file()
    assert Path(outcome.evidence_dir, "error_report.md").is_file()
    assert len(quiet_notifications["relaunch"]) == 1

    # A replacement that fails again is reported and never retried.
    again = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=_ok_quiescence,
        run_probe=lambda modules, binding_checks=None: _ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=fake_execute,
    )
    assert again.action == "declined"
    assert len(launched) == 1


def test_healer_defers_when_probe_fails(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
) -> None:
    _ = tmp_home
    target = _target(failed_row)
    outcome = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=_ok_quiescence,
        run_probe=lambda modules, binding_checks=None: SimpleNamespace(
            ok=False, failures=("sase.foo: broke",), detail="broke"
        ),
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=lambda plan, files: (_ for _ in ()).throw(
            AssertionError("must not execute")
        ),
    )
    assert outcome.action == "deferred"
    assert not quiet_notifications["relaunch"]


def test_dead_launching_claim_settles_without_relaunching(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
) -> None:
    _ = tmp_home
    import sase.agent.auto_restart.ledger as ledger_mod

    target = _target(failed_row)
    first = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=lambda: SimpleNamespace(
            ok=False, reason="noisy", quiet_seconds=0.0
        ),
        run_probe=lambda modules, binding_checks=None: _ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=lambda plan, files: (_ for _ in ()).throw(
            AssertionError("must not execute")
        ),
    )
    assert first.action == "deferred"
    assert first.ledger_key is not None
    stored = ledger_mod.load_ledger_record(first.ledger_key)
    assert stored is not None
    # Simulate a crash mid-launch: launching state, claimer long dead.
    stored = ledger_mod.advance_ledger_record(stored, "reclaim")
    stored = ledger_mod.advance_ledger_record(stored, "begin_launch")
    dead = ledger_mod.StoredLedgerRecord(
        record=stored.record,
        extra={**stored.extra, "python_claimer_pid": 2**30},
    )
    ledger_mod.store_ledger_record(dead)

    def _must_not_run(plan: Any, files: Any) -> Any:
        raise AssertionError("a second pass must never launch twice")

    outcome = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=_ok_quiescence,
        run_probe=lambda modules, binding_checks=None: _ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=_must_not_run,
    )
    assert outcome.action == "declined"
    assert outcome.reason == "launch_aborted"
    assert quiet_notifications["resurface"]


def test_live_launching_claim_defers(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
) -> None:
    _ = tmp_home
    _ = quiet_notifications
    import sase.agent.auto_restart.ledger as ledger_mod

    target = _target(failed_row)
    first = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=lambda: SimpleNamespace(
            ok=False, reason="noisy", quiet_seconds=0.0
        ),
        run_probe=lambda modules, binding_checks=None: _ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=lambda plan, files: (_ for _ in ()).throw(
            AssertionError("must not execute")
        ),
    )
    assert first.ledger_key is not None
    stored = ledger_mod.load_ledger_record(first.ledger_key)
    assert stored is not None
    # Our own process still holds the claim: the pass is live.
    stored = ledger_mod.advance_ledger_record(stored, "reclaim")
    stored = ledger_mod.advance_ledger_record(stored, "begin_launch")
    assert stored.extra["python_claimer_pid"] == os.getpid()
    outcome = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=_ok_quiescence,
        run_probe=lambda modules, binding_checks=None: _ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=lambda plan, files: (_ for _ in ()).throw(
            AssertionError("must not execute")
        ),
    )
    assert outcome.action == "deferred"
    assert outcome.reason == "launch_in_flight"
