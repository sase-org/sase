"""Ledger-claim lifecycle tests for the update-skew healer.

Split from ``tests.test_agent_auto_restart_healer``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.auto_restart.healer import HealerTarget, heal_one
from tests._agent_auto_restart_healer_helpers import (
    healer_failed_row,  # noqa: F401 (registers the failed_row fixture)
    healer_quiet_notifications,  # noqa: F401 (registers quiet_notifications)
    healer_target,
    healer_tmp_home,  # noqa: F401 (registers the tmp_home fixture)
    ok_probe_result,
    ok_quiescence,
    plan_double,
    relaunch_verdict,
)

__all__ = [
    "test_dead_launching_claim_settles_without_relaunching",
    "test_decline_matrix_silenced_vs_quiet",
    "test_deferral_expires_from_first_claim_across_retakes",
    "test_expired_deferred_claim_escalates_loudly",
    "test_live_launching_claim_defers",
    "test_replacement_failure_escalates_once_and_marks_recovery",
    "test_stale_claim_takeover_rewrites_claimer",
]


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
    done_payload = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    done_payload["recovery"] = {"state": "pending"}
    (failed_row / "done.json").write_text(json.dumps(done_payload), encoding="utf-8")
    target = healer_target(failed_row)
    base = 1_791_633_600.0
    first = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
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

    target = healer_target(failed_row)
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


def test_dead_launching_claim_settles_without_relaunching(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
) -> None:
    _ = tmp_home
    import sase.agent.auto_restart.ledger as ledger_mod

    done_payload = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    done_payload["recovery"] = {"state": "pending"}
    (failed_row / "done.json").write_text(json.dumps(done_payload), encoding="utf-8")
    target = healer_target(failed_row)
    first = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=lambda: SimpleNamespace(
            ok=False, reason="noisy", quiet_seconds=0.0
        ),
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: plan_double(target),
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
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: plan_double(target),
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

    target = healer_target(failed_row)
    first = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=lambda: SimpleNamespace(
            ok=False, reason="noisy", quiet_seconds=0.0
        ),
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: plan_double(target),
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
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: plan_double(target),
        execute_restart=lambda plan, files: (_ for _ in ()).throw(
            AssertionError("must not execute")
        ),
    )
    assert outcome.action == "deferred"
    assert outcome.reason == "launch_in_flight"


def test_deferral_expires_from_first_claim_across_retakes(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated 20s passes with max_defer 30s expire once since first claim."""
    _ = tmp_home
    import sase.config._settings_system as settings
    from sase.agent.auto_restart import ledger as ledger_mod

    monkeypatch.setattr(
        settings, "get_agent_auto_restart_max_defer_seconds", lambda: 30
    )
    done_payload = json.loads((failed_row / "done.json").read_text(encoding="utf-8"))
    done_payload["recovery"] = {"state": "pending"}
    (failed_row / "done.json").write_text(json.dumps(done_payload), encoding="utf-8")
    target = healer_target(failed_row)
    base = 1_791_633_600.0

    def _quiescence_no() -> SimpleNamespace:
        return SimpleNamespace(
            ok=False, reason="managed code is changing", quiet_seconds=0.0
        )

    first = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=_quiescence_no,
        now=base,
    )
    assert first.action == "deferred"
    stored = ledger_mod.load_ledger_record(first.ledger_key)
    assert stored is not None
    ledger_mod.store_ledger_record(
        ledger_mod.StoredLedgerRecord(
            record=stored.record,
            extra={**stored.extra, "python_claimer_pid": 2**30},
        )
    )
    second = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=_quiescence_no,
        now=base + 20,
    )
    assert second.action == "deferred"
    stored = ledger_mod.load_ledger_record(second.ledger_key)
    assert stored is not None
    ledger_mod.store_ledger_record(
        ledger_mod.StoredLedgerRecord(
            record=stored.record,
            extra={**stored.extra, "python_claimer_pid": 2**30},
        )
    )
    third = heal_one(
        target,
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=_quiescence_no,
        now=base + 40,
    )
    assert third.action == "declined"
    assert third.reason == "deferred_expired"
    assert len(quiet_notifications["escalation"]) == 1
    stored = ledger_mod.load_ledger_record(third.ledger_key)
    assert stored is not None
    assert stored.record.state == "declined"


@pytest.mark.parametrize(
    "reason", ["killed", "deferred_expired", "execute_failed", "wipe_reaches_others"]
)
@pytest.mark.parametrize("silenced", [True, False])
def test_decline_matrix_silenced_vs_quiet(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
    reason: str,
    silenced: bool,
) -> None:
    """Silenced declines are visible once; not-silenced declines stay quiet."""
    _ = tmp_home
    from sase.agent.auto_restart import ledger as ledger_mod
    from sase.agent.auto_restart._healer_common import decline_heal

    if silenced:
        done_payload = json.loads(
            (failed_row / "done.json").read_text(encoding="utf-8")
        )
        done_payload["recovery"] = {"state": "pending"}
        (failed_row / "done.json").write_text(
            json.dumps(done_payload), encoding="utf-8"
        )
    target = healer_target(failed_row)
    stored = ledger_mod.claim_ledger_record(
        key=f"test__matrix-{reason}-{silenced}-{uuid.uuid4().hex[:6]}",
        lineage_root=f"matrix-{reason}-{silenced}",
        failed_artifacts_dir=str(failed_row),
    )
    assert stored is not None
    outcome = decline_heal(
        stored,
        target,
        reason,
        f"matrix {reason}",
        now=time.time(),
        dry_run=False,
        escalate=True,
        silenced=silenced,
    )
    assert outcome.reason == reason
    if silenced:
        assert len(quiet_notifications["escalation"]) == 1
        assert not quiet_notifications["resurface"]
    else:
        assert quiet_notifications["escalation"] == []
        assert quiet_notifications["resurface"] == []
