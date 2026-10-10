"""heal_one orchestration tests for the update-skew healer.

Split from ``tests.test_agent_auto_restart_healer``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.auto_restart.healer import heal_one
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
    "test_healer_defers_when_probe_fails",
    "test_healer_relaunches_once_then_declines",
    "test_quiescence_failure_does_not_run_probe",
    "test_real_classifier_reclassifies_incident_after_probe",
]


def _execute_ok(new_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(status="ok", launched_artifacts_dir=str(new_dir), error=None)


# Healer happy path with injected fakes (ledger + evidence are real).
def test_healer_relaunches_once_then_declines(
    tmp_home: Path,
    failed_row: Path,
    quiet_notifications: dict[str, list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = tmp_home
    target = healer_target(failed_row)
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
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: plan_double(target),
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
        classify=lambda assembled: relaunch_verdict(),
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: ok_probe_result(),
        plan_restart=lambda name, follow_live_autonomy=True: plan_double(target),
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
    target = healer_target(failed_row)
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
        check_quiescence=ok_quiescence,
        run_probe=lambda modules, binding_checks=None: (
            probes.append(1)
            or SimpleNamespace(ok=False, failures=("sase.foo: broke",), detail="broke")
        ),
        plan_restart=lambda name, follow_live_autonomy=True: plan_double(target),
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
    target = healer_target(failed_row)
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
            probe_calls.append(1) or ok_probe_result()
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

    target = healer_target(failed_row)
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
        return ok_probe_result()

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
        check_quiescence=ok_quiescence,
        run_probe=probe,
        plan_restart=lambda name, follow_live_autonomy=True: plan_double(target),
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
