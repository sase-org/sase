"""Scheduled recovery, cursor progress, and competing recovery callers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import fcntl
import importlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
import yaml

from sase.agent.staged_handoff import (
    acquire_adoption_lock,
    read_adoption_receipt,
    write_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.axe.run_agent_exec_staged_recovery import recover_staged_handoff
from sase.axe.staged_handoff_reconcile import reconcile_staged_handoffs
from sase.chops.builtin import run_builtin_chop
from tests._axe_chop_output_contract_helpers import _write_context
from tests.test_staged_recovery_service import (
    STAGED_ID,
    _record,
    _settle_ok,
    _write_meta,
)


def _origin(tmp_path: Path, monkeypatch, stamp: str = "20261028120000") -> Path:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / ".sase/projects/proj/artifacts/ace-run" / stamp
    artifacts.mkdir(parents=True)
    write_staged_handoff(_record(tmp_path, "gate"), artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        STAGED_ID, "original response", artifacts_dir=str(artifacts)
    )
    _write_meta(artifacts, pid=999999)
    (artifacts / "done.json").write_text('{"outcome":"failed"}')
    _settle_ok(monkeypatch)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner", lambda *_: "dead"
    )
    return artifacts


def _publisher(monkeypatch, tmp_path: Path) -> list[str]:
    calls: list[str] = []

    def publish(_payload, *, staged_id, artifacts_dir):
        calls.append(artifacts_dir)
        return SimpleNamespace(
            record=SimpleNamespace(
                gate_id=staged_id,
                artifacts_dir=str(tmp_path / "member"),
                workspace_policy="inherit",
                member_agent_name="agent--gate",
                kind="custom",
            ),
            gate=SimpleNamespace(request_id=staged_id, notification_id="notification"),
        )

    monkeypatch.setattr("sase.gate_turn.publisher.publish_staged_gate", publish)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_gate.publish_staged_gate", publish
    )
    return calls


def test_configured_job_reaches_recovery_and_next_pass_is_noop(
    tmp_path, monkeypatch, capsys
):
    config_path = Path(__file__).parents[1] / "src/sase/default_config.yml"
    config = yaml.safe_load(config_path.read_text())
    job = next(
        job
        for job in config["axe"]["routines"]["housekeeping"]["jobs"]
        if job["name"] == "staged_handoff_reconcile"
    )
    assert job["script"] == "sase_job_staged_handoff_reconcile"
    assert job.get("trigger", "always") == "always"
    artifacts = _origin(tmp_path, monkeypatch)
    calls = _publisher(monkeypatch, tmp_path)
    importlib.import_module("sase.scripts.sase_chop_staged_handoff_reconcile")
    result_path = tmp_path / "result.json"
    context = _write_context(tmp_path, result_path)
    run_builtin_chop("staged_handoff_reconcile", ["--context", str(context)])
    assert json.loads(result_path.read_text())["counters"]["adopted"] == 1
    run_builtin_chop("staged_handoff_reconcile", ["--context", str(context)])
    assert json.loads(result_path.read_text())["status"] == "no_op"
    assert calls == [str(artifacts)]
    assert json.loads((artifacts / "done.json").read_text())["outcome"] == "failed"
    assert (
        "original response" in (artifacts / ".sase_handoff_response.json").read_text()
    )
    capsys.readouterr()


def test_candidates_survive_budget_and_one_failure_does_not_block_later_origin(
    tmp_path, monkeypatch
):
    first = _origin(tmp_path, monkeypatch)
    second = _origin(tmp_path, monkeypatch, "20261028120001")
    calls = _publisher(monkeypatch, tmp_path)
    import sase.axe.staged_handoff_reconcile as reconcile

    def recover(origin, **kwargs):
        if origin == str(first):
            raise OSError("damaged origin")
        return recover_staged_handoff(origin, **kwargs)

    monkeypatch.setattr(reconcile, "recover_staged_handoff", recover)
    one = reconcile_staged_handoffs(candidate_limit=1)
    assert one.deferred == 1 and len(one.errors) == 1
    two = reconcile_staged_handoffs(candidate_limit=1)
    assert two.adopted == 1 and not two.errors
    assert calls == [str(second)]


@pytest.mark.parametrize(
    "condition",
    ["alive", "unknown", "killed", "held", "missing", "failed", "malformed"],
)
def test_automatic_pass_never_activates_ineligible_origin(
    tmp_path, monkeypatch, condition
):
    artifacts = _origin(tmp_path, monkeypatch)
    calls = _publisher(monkeypatch, tmp_path)
    if condition in {"alive", "unknown"}:
        monkeypatch.setattr(
            "sase.axe.run_agent_exec_staged_recovery.observe_runner",
            lambda *_: condition,
        )
    elif condition == "killed":
        monkeypatch.setattr(
            "sase.axe.run_agent_exec_staged_recovery.was_killed_or_discarded",
            lambda *_: True,
        )
    elif condition == "held":
        write_adoption_receipt(
            {
                "staged_id": STAGED_ID,
                "adopted_at": "2026-10-28T12:01:00Z",
                "outcome": "handoff_not_adopted",
                "reason": "operator repair required",
            },
            artifacts_dir=str(artifacts),
        )
    elif condition == "missing":
        (artifacts / "finalizer_result.json").unlink()
    elif condition == "failed":
        monkeypatch.setattr(
            "sase.axe.run_agent_exec_staged_recovery_facts.finalizer_settlement_refusal",
            lambda *_a, **_k: "finalizer failed",
        )
    else:
        (artifacts / ".sase_handoff_staged.json").write_text("{broken")
    before = read_adoption_receipt(str(artifacts))
    for _ in range(2):
        summary = reconcile_staged_handoffs()
        assert not summary.adopted
    assert calls == []
    assert read_adoption_receipt(str(artifacts)) == before


def test_transient_probe_does_not_turn_into_explicit_hold(tmp_path, monkeypatch):
    artifacts = _origin(tmp_path, monkeypatch)
    calls = _publisher(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner", lambda *_: "alive"
    )
    assert reconcile_staged_handoffs().held == 1
    assert read_adoption_receipt(str(artifacts)) is None
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner", lambda *_: "dead"
    )
    assert reconcile_staged_handoffs().adopted == 1
    assert calls == [str(artifacts)]


def test_cli_scheduler_and_runner_race_share_one_adoption(tmp_path, monkeypatch):
    from sase.axe.run_agent_exec_staged_dispatch import (
        dispatch_completed_staged_handoff,
    )
    from tests.test_staged_recovery_service import _continuation

    artifacts = _origin(tmp_path, monkeypatch)
    calls = _publisher(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_dispatch.finalizer_settlement_refusal",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.handle_gate_marker", lambda *_a, **_k: "gated"
    )
    continuation = _continuation(tmp_path, artifacts)
    barrier = threading.Barrier(3)

    def call(which):
        barrier.wait(timeout=10)
        if which == "runner":
            return dispatch_completed_staged_handoff(str(artifacts), continuation)
        if which == "cli":
            return recover_staged_handoff(str(artifacts), mode="explicit")
        return reconcile_staged_handoffs()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(call, ["runner", "cli", "scheduler"]))
    assert all(result is not None for result in results)
    assert calls == [str(artifacts)]
    assert read_adoption_receipt(str(artifacts))["outcome"] == "adopted"


def test_deadline_keeps_pending_candidates(tmp_path, monkeypatch):
    artifacts = _origin(tmp_path, monkeypatch)
    calls = _publisher(monkeypatch, tmp_path)
    reconcile_staged_handoffs(candidate_limit=0)
    summary = reconcile_staged_handoffs(time_budget=0)
    assert summary.deferred == 1
    assert calls == []
    assert reconcile_staged_handoffs().adopted == 1
    assert calls == [str(artifacts)]


@pytest.mark.parametrize("owner", ["thread", "process"])
def test_busy_adoption_lock_does_not_block_the_sweep(tmp_path, monkeypatch, owner):
    artifacts = _origin(tmp_path, monkeypatch)
    calls = _publisher(monkeypatch, tmp_path)
    with ExitStack() as stack:
        if owner == "thread":
            stack.enter_context(acquire_adoption_lock(artifacts))
        else:
            lock = stack.enter_context((artifacts / ".sase_handoff.lock").open("a"))
            fcntl.flock(lock, fcntl.LOCK_EX)
        summary = reconcile_staged_handoffs()
        assert summary.held == 1
        assert "lock" in summary.held_details[0]
        assert read_adoption_receipt(str(artifacts)) is None
    assert reconcile_staged_handoffs().adopted == 1
    assert calls == [str(artifacts)]
