"""Resilient hijack recovery transactions: races, crashes, and refusals."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pytest

from sase.agent.hijack import preview as preview_module
from tests._agent_hijack_recovery_transaction_support import Transaction, parent_done


def _disable_provider(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    from sase.llm_provider import provider_disable_peek as peek_module

    monkeypatch.setattr(
        peek_module, "peek_active_provider_disables", lambda: {provider: object()}
    )


def test_concurrent_resolvers_create_one_request_and_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = Transaction(monkeypatch, tmp_path)
    results: list[Any] = []
    errors: list[BaseException] = []

    def attempt() -> None:
        try:
            results.append(txn.recover(action="continue"))
        except BaseException as exc:  # noqa: BLE001 - surface thread failures
            errors.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not errors
    assert len(results) == 2
    kinds = sorted(result.kind for result in results)
    assert kinds[1] == "launched"
    assert kinds[0] in {"already_resolving", "already_resolved"}
    launched = next(result for result in results if result.kind == "launched")
    waiting = next(result for result in results if result.kind != "launched")
    assert waiting.admission_request_id == launched.admission_request_id
    assert waiting.launch_identity == launched.launch_identity
    assert len(txn.bundles()) == 1
    assert len(txn.children()) == 1
    assert txn.record()["state"] == "resolved"


def test_crash_after_cas_resumes_the_same_attempt_without_a_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolver that dies after CAS leaves a resumable real attempt."""
    from sase.agent.hijack import ledger as ledger_module
    from sase.agent.hijack.recover_common import admission_request_id_for
    from sase.agent.hijack.recover_common import new_launch_identity
    from sase.agent.hijack.recover_subject import lineage_for
    from sase.agent.hijack.recovery_admission import (
        persist_prepared_recovery_descriptor,
        prepare_recovery_admission_descriptor,
    )
    from sase.agent.hijack.recover_target import resolve_effective_target
    from sase.agent.launch_submission import capture_launch_submitted_at

    txn = Transaction(monkeypatch, tmp_path)
    held = txn.record()
    preview = preview_module.hijack_recovery_preview(dict(held))
    row = preview.action("continue")
    assert row is not None
    target = resolve_effective_target(
        action="continue",
        record=held,
        preview_action={
            "available": row.available,
            "reason": row.reason,
            "target": row.target,
        },
        model_override=None,
        prompt_text=None,
    )
    launch_identity = new_launch_identity()
    request_id = admission_request_id_for("h-123", launch_identity)
    descriptor = prepare_recovery_admission_descriptor(
        record=held,
        action=target.action,
        target=target.concrete_target,
        model_changed=target.model_changed,
        prompt="prepared",
        context_mode="fork",
        reserved_successor_name="acme--4",
        session_base="acme",
        project_name="proj",
        launch_identity=launch_identity,
        admission_request_id=request_id,
        lineage=lineage_for(hijack_id="h-123", record=held, target=target),
        resolver_pid=os.getpid(),
        resolver_process_identity_token=None,
        attempt_revision=int(held.get("revision", 0)) + 1,
        launch_submitted_at=capture_launch_submitted_at(),
    )
    persist_prepared_recovery_descriptor(descriptor)
    # The crash happens here: begin_resolution is the last write. A fresh
    # coordinator process reconstructs from the same durable evidence. The
    # event carries the full reservation the Rust machine requires.
    resolving = ledger_module.cas_advance_record(
        dict(held),
        {
            "event": "begin_resolution",
            "action": target.action,
            "reserved_successor_name": "acme--4",
            "concrete_target_model": target.concrete_target,
            "model_changed": target.model_changed,
            "resolver_pid": os.getpid(),
            "launch_identity": launch_identity,
            "admission_request_id": request_id,
            "admission_identity": descriptor["dispatch_fingerprint"],
        },
    )
    assert resolving["state"] == "resolving"

    resumed = txn.recover(action="continue")

    # The fresh resolver re-dispatches the same durable attempt exactly
    # once; settlement stays with reconciliation, so the record resolves
    # nothing yet and no duplicate request or child may appear. The resume
    # reports the dispatch (exit 0), not a refusal.
    assert resumed.kind == "launched"
    assert resumed.admission_request_id == request_id
    assert resumed.launch_identity == launch_identity
    assert len(txn.bundles()) == 1
    assert len(txn.children()) == 1
    assert len(txn.provider_calls) == 1
    assert txn.record()["state"] == "resolving"

    again = txn.recover(action="continue")

    assert again.kind == "launched"
    assert again.admission_request_id == request_id
    assert len(txn.bundles()) == 1
    assert len(txn.children()) == 1
    assert len(txn.provider_calls) == 1


def test_uncertain_spawn_keeps_resolving_and_resumes_the_same_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = Transaction(monkeypatch, tmp_path)
    txn.spawn_mode = "lost_contact"
    first = txn.recover(action="continue")

    assert first.kind == "uncertain"
    assert txn.record()["state"] == "resolving"
    assert txn.record()["launch_stage"] == "dispatching"
    assert txn.children() == []
    assert txn.provider_calls == []

    resumed = txn.recover(action="continue")

    assert resumed.kind == "queued"
    assert resumed.admission_request_id == first.admission_request_id
    assert resumed.launch_identity == first.launch_identity
    assert resumed.detail["admission"]["state"] == "dispatching"
    assert len(txn.bundles()) == 1
    assert txn.children() == []
    assert txn.record()["state"] == "resolving"


def test_cancel_of_uncertain_dispatch_retains_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack.recovery_admission import (
        cancel_recovery_admission_request,
        observe_recovery_admission,
    )
    from sase.agent.launch_admission import run_coordinator_in_bundle

    txn = Transaction(monkeypatch, tmp_path)
    txn.spawn_mode = "lost_contact"
    first = txn.recover(action="continue")
    assert first.kind == "uncertain"

    # Cancelling an uncertain dispatch proves nothing: the journal stays
    # dispatching and the record retains resolving for reconciliation.
    cancelled = cancel_recovery_admission_request(
        str(first.admission_request_id), reason="stop request"
    )

    assert cancelled["state"] == "dispatching"
    assert cancelled["admission_complete"] is False
    assert txn.record()["state"] == "resolving"
    status = observe_recovery_admission(str(first.admission_request_id))
    assert status["state"] == "dispatching"
    # A fresh coordinator reads the same bundle and still cannot finish it.
    bundle = txn.bundles()[0]
    progress = run_coordinator_in_bundle(bundle)
    assert progress.complete is False
    assert txn.children() == []
    assert txn.provider_calls == []
    assert observe_recovery_admission(str(first.admission_request_id))["state"] == (
        "dispatching"
    )


def test_disabled_provider_refuses_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = Transaction(monkeypatch, tmp_path)
    _disable_provider(monkeypatch, "claude")

    result = txn.recover(action="continue")

    assert result.kind == "refused"
    assert result.detail["code"] == "provider_disabled"
    assert txn.record()["state"] == "held"
    assert txn.spawned_prompts == []
    assert txn.children() == []
    assert txn.bundles() == []


def test_failed_inheritance_never_runs_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The child boots with a bead the predecessor never held, so the real
    # bootstrap gate refuses before the provider boundary is reached.
    txn = Transaction(monkeypatch, tmp_path)
    txn.child_bead = "sase-999"

    result = txn.recover(action="continue")

    assert result.kind == "error"
    assert result.detail["code"] == "launch_failed"
    assert txn.record()["state"] == "held"
    assert txn.provider_calls == []


def test_failed_termination_retains_resolving_for_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = Transaction(monkeypatch, tmp_path)
    txn.terminate_verified = False
    txn.ack_overrides = {"launch_identity": "wrong-identity"}

    result = txn.recover(action="continue")

    assert result.kind == "uncertain"
    assert txn.record()["state"] == "resolving"
    assert txn.terminations == [txn.pid]
    assert "safe rollback is unproven" in result.message
    assert result.detail["rollback"]["outcome"] != "return_to_held"


def test_interrupted_settlement_replays_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import recover_settle as settle_module
    from sase.agent.hijack.recover_settle import settle_recovery

    txn = Transaction(monkeypatch, tmp_path)
    calls = {"writes": 0}
    real_write = settle_module._write_predecessor_settlement

    def fail_once(*args: Any, **kwargs: Any) -> None:
        calls["writes"] += 1
        if calls["writes"] == 1:
            raise OSError("simulated crash between CAS and done.json")
        real_write(*args, **kwargs)

    monkeypatch.setattr(settle_module, "_write_predecessor_settlement", fail_once)
    with pytest.raises(OSError, match="simulated crash"):
        txn.recover(action="continue")

    # The CAS landed but the marker write did not: still resolving's
    # successor, done.json without recovery fields, outcome untouched.
    resolved = txn.record()
    assert resolved["state"] == "resolved"
    assert resolved["reserved_successor_name"] == "acme--4"
    done = parent_done(txn)
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["state"] == "pending"
    revision_after_crash = resolved["revision"]

    # Replaying the real settlement helper repairs only the marker: no new
    # CAS, no duplicate successor, same resolved revision. The fault only
    # fires once, so the replayed write goes through.
    replayed = settle_recovery(
        dict(resolved),
        action="continue",
        successor_name="acme--4",
    )

    assert replayed["state"] == "resolved"
    assert replayed["revision"] == revision_after_crash
    done = parent_done(txn)
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["state"] == "resolved"
    assert done["recovery"]["successor"] == "acme--4"
    assert calls["writes"] == 2
