"""Skip, storm, probe, gate, and target-order tests for the healer.

Split from ``tests.test_agent_auto_restart_healer``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from sase.agent.auto_restart._healer_common import apply_skip_rules
from sase.agent.auto_restart.healer import HealerTarget
from sase.agent.auto_restart.probe import run_probe
from sase.agent.auto_restart.quiescence import check_quiescence
from tests._agent_auto_restart_healer_helpers import (
    healer_failed_row,  # noqa: F401 (registers the failed_row fixture)
    healer_target,
    healer_tmp_home,  # noqa: F401 (registers the tmp_home fixture)
)

__all__ = [
    "test_attach_provenance_fills_from_identity_and_file_proof",
    "test_claimer_liveness_dead_pid_and_self",
    "test_gate_off_when_config_disabled",
    "test_gate_on_when_config_enabled",
    "test_no_skip_for_plain_failed_row",
    "test_pending_targets_are_topological_then_least_progress_first",
    "test_probe_imports_stdlib_cleanly",
    "test_probe_reports_missing_module",
    "test_quiescence_returns_a_reason",
    "test_skip_already_restarted",
    "test_skip_killed_outcome",
    "test_skip_non_failed_row",
    "test_skip_remote_row",
    "test_storm_breaker_trips_and_resume_rearms",
    "test_storm_window_counts_only_launches",
]


# Skip rules: user intent wins.
def test_skip_already_restarted(failed_row: Path) -> None:
    meta_path = failed_row / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["auto_restart"] = {"ledger_key": "sase__abc"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    done = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    decision = apply_skip_rules(healer_target(failed_row), done=done, meta=meta)
    assert decision.skip
    assert decision.decline_reason == "already_restarted"


def test_skip_killed_outcome(failed_row: Path) -> None:
    done = {"outcome": "killed", "kill_source": "user"}
    decision = apply_skip_rules(healer_target(failed_row), done=done, meta={})
    assert decision.skip
    assert decision.decline_reason == "killed"
    assert not decision.loud


def test_skip_non_failed_row(failed_row: Path) -> None:
    done = {"outcome": "done"}
    decision = apply_skip_rules(healer_target(failed_row), done=done, meta={})
    assert decision.skip
    assert decision.decline_reason == "no_longer_failed"


def test_skip_remote_row(failed_row: Path) -> None:
    done = {"outcome": "failed", "is_remote": True}
    decision = apply_skip_rules(healer_target(failed_row), done=done, meta={})
    assert decision.skip
    assert decision.decline_reason == "remote"


def test_no_skip_for_plain_failed_row(failed_row: Path) -> None:
    done = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    decision = apply_skip_rules(healer_target(failed_row), done=done, meta={})
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
    assert "sase@abc" not in decision.reason
    assert decision.reason.startswith("4 agents broke within one update")
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


def test_attach_provenance_fills_from_identity_and_file_proof(
    tmp_path: Path,
) -> None:
    """Provenance falls back to W1 identity revs and W3 file proof."""
    from types import SimpleNamespace

    from sase.agent.auto_restart.healer_relaunch import _attach_provenance
    from sase.agent.auto_restart.provenance import PROVENANCE_ENV

    target = HealerTarget(
        artifacts_dir=tmp_path / "20261009T120000",
        project="sase",
        agent_name="prov-agent",
    )
    witnesses = SimpleNamespace(
        refresh_log_line=None,
        boot_identity="sase@aaa111|other@zzz",
        current_identity="sase@bbb222|other@zzz",
        file_proof=SimpleNamespace(
            culprit_commit="ccc333",
            culprit_subject="remove symbol",
        ),
    )
    facts = SimpleNamespace(lifecycle_phase="waiting")
    verdict = SimpleNamespace(signature="ImportError: x", phase_class="pre_provider")
    plan = SimpleNamespace(
        force_reuse_plan=SimpleNamespace(segment_envs=[{}]),
    )
    import json as _json

    _attach_provenance(
        plan,
        target,
        verdict=verdict,
        episode_id=None,
        lineage_root="20261009T120000",
        ledger_key="sase__20261009T120000",
        evidence_dir=None,
        evidence_files={},
        witnesses=witnesses,
        facts=facts,
    )
    provenance = _json.loads(plan.force_reuse_plan.segment_envs[0][PROVENANCE_ENV])
    assert provenance["from_rev"] == "aaa111"
    assert provenance["to_rev"] == "bbb222"
    assert provenance["culprit_commit"] == "ccc333"
    assert provenance["culprit_subject"] == "remove symbol"
    assert "waiting" in (provenance["broke_detail"] or "")
