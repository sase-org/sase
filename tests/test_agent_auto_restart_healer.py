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

    base = 1_791_633_600.0
    old = ledger_mod.claim_ledger_record(
        key=f"test__old-launch-{uuid.uuid4().hex[:8]}",
        lineage_root="old-launch",
        at=ledger_mod.timestamp_for(base - 1801),
    )
    current = ledger_mod.claim_ledger_record(
        key=f"test__current-launch-{uuid.uuid4().hex[:8]}",
        lineage_root="current-launch",
        at=ledger_mod.timestamp_for(base - 1799),
    )
    assert old is not None and current is not None
    old = ledger_mod.advance_ledger_record(
        old, "begin_launch", at=ledger_mod.timestamp_for(base - 1801)
    )
    old = ledger_mod.advance_ledger_record(
        old, "launched", at=ledger_mod.timestamp_for(base - 1801)
    )
    current = ledger_mod.advance_ledger_record(
        current, "begin_launch", at=ledger_mod.timestamp_for(base - 1799)
    )
    current = ledger_mod.advance_ledger_record(
        current, "launched", at=ledger_mod.timestamp_for(base - 1799)
    )
    assert storm_mod.storm_check(
        [old],
        episode_id=None,
        max_per_episode=20,
        max_per_30m=1,
        now=base,
    ).allowed
    assert not storm_mod.storm_check(
        [current],
        episode_id=None,
        max_per_episode=20,
        max_per_30m=1,
        now=base,
    ).allowed


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
    classifications: list[bool] = []

    def classify(assembled: Any) -> SimpleNamespace:
        has_probe = assembled.witnesses.probe is not None
        classifications.append(has_probe)
        if not has_probe:
            return SimpleNamespace(
                mode="defer",
                reason="probe_pending",
                reason_text="waiting for probe",
                episode_id="sase@9fd8a08",
            )
        return SimpleNamespace(
            mode="defer",
            reason="probe_failed",
            reason_text="probe witness failed",
            episode_id="sase@9fd8a08",
        )

    probes: list[int] = []
    outcome = heal_one(
        target,
        classify=classify,
        check_quiescence=_ok_quiescence,
        run_probe=lambda modules, binding_checks=None: (
            probes.append(1)
            or SimpleNamespace(ok=False, failures=("sase.foo: broke",), detail="broke")
        ),
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=lambda plan, files: (_ for _ in ()).throw(
            AssertionError("must not execute")
        ),
    )
    assert outcome.action == "deferred"
    assert classifications == [False, True]
    assert probes == [1]
    assert not quiet_notifications["relaunch"]


def test_quiescence_failure_does_not_run_probe(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
) -> None:
    _ = tmp_home
    _ = quiet_notifications
    target = _target(failed_row)
    probe_calls: list[int] = []
    verdict = SimpleNamespace(
        mode="defer",
        reason="probe_pending",
        reason_text="waiting for probe",
        episode_id="sase@9fd8a08",
    )
    outcome = heal_one(
        target,
        classify=lambda assembled: verdict,
        check_quiescence=lambda: SimpleNamespace(
            ok=False, reason="code is still changing", quiet_seconds=0.0
        ),
        run_probe=lambda modules, binding_checks=None: (
            probe_calls.append(1) or _ok_probe_result()
        ),
    )
    assert outcome.action == "deferred"
    assert outcome.reason_text == "code is still changing"
    assert not probe_calls


def test_real_classifier_reclassifies_incident_after_probe(
    tmp_home: Path,
    failed_row: Path,
) -> None:
    _ = tmp_home
    from sase.agent.auto_restart.managed_roots import current_code_identity
    from sase.agent.auto_restart.provenance import PROVENANCE_ENV

    target = _target(failed_row)
    identity = current_code_identity()
    roots = [dict(root) for root in identity.get("roots", [])]
    sase_root = next(root for root in roots if root.get("name") == "sase")
    sase_root["commit"] = "9c5000f2dbb126962ea0a84856d0a49115450dc7"
    metadata = json.loads((failed_row / "agent_meta.json").read_text())
    metadata.update(
        {
            "booted_at": "2026-10-09T11:55:00+00:00",
            "code_identity": {**identity, "roots": roots},
        }
    )
    (failed_row / "agent_meta.json").write_text(json.dumps(metadata))
    log_path = failed_row / "runner.log"
    log_path.write_text(
        "Refreshing sase runner code after dependency wait: "
        "9c5000f2dbb126962ea0a84856d0a49115450dc7 -> "
        "9fd8a081f45689655249b7bf6ed7b561de65b8bf\n"
    )
    done = json.loads((failed_row / "done.json").read_text())
    done.update(
        {
            "error": (
                "ImportError: cannot import name 'auto_launch_prefix' from "
                "'sase.monitor.continuation_delivery'"
            ),
            "traceback": "ImportError in sase.monitor.continuation_delivery",
            "output_path": str(log_path),
            "failure_facts": {
                "schema_version": 1,
                "lifecycle_phase": "waiting",
                "skew_suspect": True,
                "import_error": {
                    "name": "sase.monitor.continuation_delivery",
                    "missing_symbol": "auto_launch_prefix",
                },
            },
        }
    )
    (failed_row / "done.json").write_text(json.dumps(done))

    probes: list[tuple[list[str], list[tuple[str, str]]]] = []
    launched_dir = failed_row.parent / "20261009T120100"

    def probe(
        modules: list[str], binding_checks: list[tuple[str, str]] | None = None
    ) -> SimpleNamespace:
        probes.append((modules, binding_checks or []))
        return _ok_probe_result()

    def execute(plan: Any, evidence_files: dict[str, Any]) -> SimpleNamespace:
        new_dir = launched_dir
        new_dir.mkdir(exist_ok=True)
        environment = plan.force_reuse_plan.segment_envs[0]
        provenance = json.loads(environment[PROVENANCE_ENV])
        recovery = json.loads((failed_row / "done.json").read_text())["recovery"]
        assert provenance["from_rev"] == "9c5000f2dbb126962ea0a84856d0a49115450dc7"
        assert provenance["to_rev"] == "9fd8a081f45689655249b7bf6ed7b561de65b8bf"
        assert "waiting" in provenance["broke_detail"]
        assert recovery["state"] == "launching"
        assert recovery["ledger_key"] == provenance["ledger_key"]
        assert recovery["episode_id"] == provenance["episode_id"]
        assert "verdict.json" in evidence_files
        return _execute_ok(new_dir)

    outcome = heal_one(
        target,
        check_quiescence=_ok_quiescence,
        run_probe=probe,
        plan_restart=lambda name, follow_live_autonomy=True: _plan_double(target),
        execute_restart=execute,
        now=1_791_633_600.0,
    )

    assert outcome.action == "relaunched", outcome.reason_text
    assert len(probes) == 1
    assert "sase.monitor.continuation_delivery" in probes[0][0]
    from sase.agent.auto_restart import ledger as ledger_mod

    stored = ledger_mod.load_ledger_record(outcome.ledger_key)
    assert stored is not None
    assert stored.record.state == "launched"
    assert stored.record.claimed_at == ledger_mod.timestamp_for(1_791_633_600.0)
    assert all(entry.at for entry in stored.record.history)


def test_expired_deferred_claim_escalates_loudly(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    import sase.config._settings_system as settings
    from sase.agent.auto_restart import ledger as ledger_mod

    monkeypatch.setattr(
        settings, "get_agent_auto_restart_max_defer_seconds", lambda: 30
    )
    target = _target(failed_row)
    base = 1_791_633_600.0
    first = heal_one(
        target,
        classify=lambda assembled: _relaunch_verdict(),
        check_quiescence=lambda: SimpleNamespace(
            ok=False, reason="managed code is changing", quiet_seconds=0.0
        ),
        now=base,
    )
    assert first.action == "deferred"
    stored = ledger_mod.load_ledger_record(first.ledger_key)
    assert stored is not None
    stale = ledger_mod.StoredLedgerRecord(
        record=stored.record,
        extra={**stored.extra, "python_claimer_pid": 2**30},
    )
    ledger_mod.store_ledger_record(stale)

    expired = heal_one(target, now=base + 31)

    assert expired.action == "declined"
    assert expired.reason == "deferred_expired"
    assert "Couldn't restart" in expired.reason_text
    assert len(quiet_notifications["escalation"]) == 1
    assert "Couldn't restart" in quiet_notifications["escalation"][0]["title"]
    recovery = json.loads((failed_row / "done.json").read_text())["recovery"]
    assert recovery["ledger_key"] == first.ledger_key
    assert recovery["episode_id"] == "sase@9fd8a08"


@pytest.mark.parametrize("initial_state", ["claimed", "deferred"])
def test_stale_claim_takeover_rewrites_claimer(
    tmp_home: Path,
    failed_row: Path,
    initial_state: str,
) -> None:
    _ = tmp_home
    import os

    from sase.agent.auto_restart import ledger as ledger_mod

    target = _target(failed_row)
    base = 1_791_633_600.0
    lineage_root = target.artifacts_dir.name
    stored = ledger_mod.claim_ledger_record(
        key=ledger_mod.ledger_key(target.project, lineage_root),
        lineage_root=lineage_root,
        failed_artifacts_dir=str(failed_row),
        at=ledger_mod.timestamp_for(base),
    )
    assert stored is not None
    if initial_state == "deferred":
        stored = ledger_mod.advance_ledger_record(
            stored, "defer", at=ledger_mod.timestamp_for(base)
        )
    stale = ledger_mod.StoredLedgerRecord(
        record=stored.record,
        extra={**stored.extra, "python_claimer_pid": 2**30},
    )
    ledger_mod.store_ledger_record(stale)

    heal_one(
        target,
        classify=lambda assembled: SimpleNamespace(
            mode="decline",
            reason="test_done",
            reason_text="test claim takeover",
            episode_id=None,
        ),
        now=base + 10,
    )

    reclaimed = ledger_mod.load_ledger_record(stored.record.key)
    assert reclaimed is not None
    assert reclaimed.extra["python_claimer_pid"] == os.getpid()
    assert reclaimed.extra["python_claimer_identity"]
    if initial_state == "deferred":
        assert reclaimed.record.claimed_at == ledger_mod.timestamp_for(base + 10)


def test_replacement_failure_escalates_once_and_marks_recovery(
    tmp_home: Path,
    tmp_path: Path,
    quiet_notifications: dict[str, list],
) -> None:
    _ = tmp_home
    from sase.agent.auto_restart import ledger as ledger_mod

    original = tmp_path / "artifacts" / "20261009T120000"
    original.mkdir(parents=True)
    replacement = tmp_path / "artifacts" / "20261009T120100"
    replacement.mkdir(parents=True)
    key = f"sase__replacement-{uuid.uuid4().hex[:8]}"
    stored = ledger_mod.claim_ledger_record(
        key=key,
        lineage_root="replacement-lineage",
        failed_artifacts_dir=str(original),
    )
    assert stored is not None
    stored = ledger_mod.advance_ledger_record(stored, "begin_launch")
    stored = ledger_mod.advance_ledger_record(stored, "launched")
    from sase.agent.auto_restart._healer_common import annotate_record

    stored = annotate_record(stored, episode_id="sase@9fd8a08")
    (replacement / "done.json").write_text(
        json.dumps({"outcome": "failed", "error": "broke again"})
    )
    (replacement / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "replacement-agent",
                "auto_restart": {
                    "ledger_key": key,
                    "episode_id": "sase@9fd8a08",
                    "lineage_root": "replacement-lineage",
                },
            }
        )
    )
    target = HealerTarget(
        artifacts_dir=replacement, project="sase", agent_name="replacement-agent"
    )

    first = heal_one(target)
    again = heal_one(target)

    assert first.reason == "already_restarted"
    assert again.reason == "already_restarted"
    assert len(quiet_notifications["escalation"]) == 1
    title = quiet_notifications["escalation"][0]["title"]
    assert (
        "This was its automatic restart after sase update 9fd8a08 — not retrying."
        in title
    )
    settled = ledger_mod.load_ledger_record(key)
    assert settled is not None and settled.record.state == "settled_failed"
    recovery = json.loads((replacement / "done.json").read_text())["recovery"]
    assert recovery["state"] == "declined"
    assert recovery["reason"] == "already_restarted"
    assert recovery["ledger_key"] == key
    assert recovery["episode_id"] == "sase@9fd8a08"


def test_pending_targets_are_topological_then_least_progress_first(
    tmp_path: Path,
) -> None:
    from sase.agent.auto_restart.healer_targets import _order_targets

    waiter_dir = tmp_path / "waiter"
    independent_dir = tmp_path / "independent"
    dependency_dir = tmp_path / "dependency"
    targets = [
        HealerTarget(waiter_dir, "sase", "waiter"),
        HealerTarget(independent_dir, "sase", "independent"),
        HealerTarget(dependency_dir, "sase", "dependency"),
    ]
    for directory in (waiter_dir, independent_dir, dependency_dir):
        directory.mkdir()
    (waiter_dir / "waiting.json").write_text(
        json.dumps({"waiting_for": ["dependency"]})
    )
    os.utime(independent_dir, (10, 10))
    os.utime(dependency_dir, (20, 20))
    os.utime(waiter_dir, (1, 1))

    ordered = _order_targets(targets)

    assert [target.agent_name for target in ordered] == [
        "independent",
        "dependency",
        "waiter",
    ]


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
