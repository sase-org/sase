"""Idempotent recovery-submission tests: one stable proc per close token.

Covers deterministic proc identity, the launch-permit gate, crash-replay
resumption without new proc minting, consumed terminal rows, and refusal
paths (failed publish, corrupt claims, losing publishers, stale tokens).
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

import pytest

from sase.bead.recovery import RecoveryPublicationResult
from sase.bead.recovery_submit import (
    OUTCOME_ABORTED,
    OUTCOME_CONSUMED,
    OUTCOME_REPLAYED,
    OUTCOME_SUBMITTED,
    RECOVERY_PROC_ORIGIN,
    SASE_RECOVERY_CLOSE_TOKEN_ENV,
    RecoveryClaim,
    RecoveryGuardError,
    RecoveryLaunchGuard,
    check_recovery_close_token,
    default_owner_machine,
    recovery_claim_request,
    recovery_concurrency_keys,
    recovery_guard_from_env,
    recovery_proc_id,
    recovery_proc_request,
    recovery_request_fingerprint,
    submit_recovery_launch,
    submit_recovery_launch_in_store,
)
from sase.bead.zombie import ZombieReport
from sase.core.zombie_facade import ZombieEvaluationReport, ZombieVerdict
from sase.procs.models import Proc
from sase.procs.request import ProcSubmitRequest

PROJECT = "alpha"
EPIC = "demo-1"
TOKEN = "demo-1.4:evt-9"
OTHER_TOKEN = "demo-1.4:evt-10"


def _claim_key(project_id: str, epic_id: str, close_token: str) -> str:
    digest = sha256()
    digest.update(project_id.encode())
    digest.update(b"\x00")
    digest.update(epic_id.encode())
    digest.update(b"\x00")
    digest.update(close_token.encode())
    return digest.hexdigest()


@pytest.fixture
def fake_claim_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.bead.recovery_submit.recovery_claim_key", _claim_key)


def _claim(
    *,
    project: str = PROJECT,
    epic: str = EPIC,
    token: str = TOKEN,
    owner: str = "athena",
    proc_id: str = "",
    fingerprint: str = "",
) -> RecoveryClaim:
    key = _claim_key(project, epic, token)
    return RecoveryClaim(
        project_id=project,
        epic_id=epic,
        close_token=token,
        owner_machine=owner,
        proc_id=proc_id or f"epic-recovery-{key}",
        request_fingerprint=fingerprint or f"epic-recovery:{key}",
        activation_generation=1,
        created_at="2026-11-28T12:00:00Z",
    )


def _permit(claim: RecoveryClaim) -> RecoveryPublicationResult:
    return RecoveryPublicationResult(
        launch_permit=True,
        reason="local_winner_published",
        published=True,
        local_winner=True,
        claim=claim,
    )


def _no_permit(reason: str) -> RecoveryPublicationResult:
    return RecoveryPublicationResult(
        launch_permit=False,
        reason=reason,
        published=False,
        local_winner=False,
    )


def _zombie_row(
    *,
    epic: str = EPIC,
    token: str = TOKEN,
    eligible: bool = True,
    state: str = "zombie",
) -> ZombieVerdict:
    return ZombieVerdict(
        plan_id=epic,
        title="Demo epic",
        state=state,
        zombie=state == "zombie",
        recovery_eligible=eligible,
        close_token=token,
    )


def _report(
    *rows: ZombieVerdict, failed: bool = False, reason: str | None = None
) -> ZombieReport:
    return ZombieReport(
        report=ZombieEvaluationReport(rows=tuple(rows)),
        project=PROJECT,
        titles={},
        generated_at=0.0,
        collection_failed=failed,
        failure_reason=reason,
    )


def _proc(proc_id: str, status: str) -> Proc:
    return Proc(
        proc_id=proc_id,
        label="Epic recovery",
        kind="command",
        status=status,
        command=["sase", "bead", "work"],
        cwd="/tmp",
        origin="axe",
        created_at="2026-11-28T12:00:00Z",
        log_path="/tmp/recovery.log",
    )


def test_proc_identity_is_deterministic(fake_claim_key: None) -> None:
    first = recovery_proc_id(PROJECT, EPIC, TOKEN)
    assert first == recovery_proc_id(PROJECT, EPIC, TOKEN)
    assert first.startswith("epic-recovery-")
    assert recovery_request_fingerprint(PROJECT, EPIC, TOKEN) == (
        recovery_request_fingerprint(PROJECT, EPIC, TOKEN)
    )
    assert recovery_proc_id(PROJECT, EPIC, OTHER_TOKEN) != first
    assert recovery_request_fingerprint(
        PROJECT, EPIC, OTHER_TOKEN
    ) != recovery_request_fingerprint(PROJECT, EPIC, TOKEN)
    assert recovery_concurrency_keys(PROJECT, EPIC, TOKEN) == (
        f"epic-recovery:{PROJECT}:{EPIC}:{TOKEN}",
    )


def test_proc_identity_is_project_scoped(fake_claim_key: None) -> None:
    mine = recovery_proc_id(PROJECT, EPIC, TOKEN)
    theirs = recovery_proc_id("beta", EPIC, TOKEN)
    assert mine != theirs
    assert recovery_request_fingerprint(
        PROJECT, EPIC, TOKEN
    ) != recovery_request_fingerprint("beta", EPIC, TOKEN)


def test_proc_request_reaches_bead_work_for_epic_id(
    fake_claim_key: None,
) -> None:
    request = recovery_proc_request(project=PROJECT, epic_id=EPIC, close_token=TOKEN)
    assert request.command == ["sase", "bead", "work", EPIC, "--yes-to-all"]
    assert request.origin == RECOVERY_PROC_ORIGIN == "axe"
    assert request.project == PROJECT
    assert request.proc_id == recovery_proc_id(PROJECT, EPIC, TOKEN)
    assert request.request_fingerprint == recovery_request_fingerprint(
        PROJECT, EPIC, TOKEN
    )
    assert tuple(request.concurrency_keys) == recovery_concurrency_keys(
        PROJECT, EPIC, TOKEN
    )
    assert request.env == {SASE_RECOVERY_CLOSE_TOKEN_ENV: TOKEN}
    assert list(request.tags) == ["epic-recovery"]
    # The target is the existing epic bead id dispatched through the bead-id
    # work path: no plan-file argument and no plan-file launch helper.
    assert (request.command or [])[1:4] == ["bead", "work", EPIC]
    assert not any(str(part).endswith(".md") for part in request.command or [])


def test_claim_request_carries_stable_identity(fake_claim_key: None) -> None:
    request = recovery_claim_request(
        project=PROJECT, epic_id=EPIC, close_token=TOKEN, owner_machine="athena"
    )
    assert request == {
        "project_id": PROJECT,
        "epic_id": EPIC,
        "close_token": TOKEN,
        "owner_machine": "athena",
        "proc_id": recovery_proc_id(PROJECT, EPIC, TOKEN),
        "request_fingerprint": recovery_request_fingerprint(PROJECT, EPIC, TOKEN),
    }
    assert default_owner_machine()


def test_guard_from_env_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SASE_RECOVERY_CLOSE_TOKEN_ENV, raising=False)
    assert recovery_guard_from_env(PROJECT) is None

    monkeypatch.setenv(SASE_RECOVERY_CLOSE_TOKEN_ENV, TOKEN)
    guard = recovery_guard_from_env(PROJECT)
    assert guard == RecoveryLaunchGuard(project=PROJECT, expected_close_token=TOKEN)

    with pytest.raises(RecoveryGuardError):
        recovery_guard_from_env(None)
    with pytest.raises(RecoveryGuardError):
        recovery_guard_from_env("   ")


def test_submit_publishes_then_submits(fake_claim_key: None) -> None:
    claim = _claim()
    seen: dict[str, Any] = {}

    def fake_publish(project: str, request: dict[str, Any]) -> Any:
        seen["project"] = project
        seen["request"] = dict(request)
        return _permit(claim)

    submitted: list[ProcSubmitRequest] = []

    def fake_submit(request: ProcSubmitRequest) -> Proc:
        submitted.append(request)
        return _proc(claim.proc_id, "pending")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        owner_machine="athena",
        publish_claim=fake_publish,
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(_zombie_row()),
        submit_proc=fake_submit,
    )
    assert result.outcome == OUTCOME_SUBMITTED
    assert result.proc is not None and result.proc.proc_id == claim.proc_id
    assert result.claim == claim
    assert seen["project"] == PROJECT
    assert seen["request"]["proc_id"] == claim.proc_id
    assert seen["request"]["request_fingerprint"] == claim.request_fingerprint
    assert seen["request"]["owner_machine"] == "athena"
    assert len(submitted) == 1
    assert submitted[0].origin == "axe"
    assert submitted[0].env == {SASE_RECOVERY_CLOSE_TOKEN_ENV: TOKEN}


def test_submit_without_permit_never_submits(fake_claim_key: None) -> None:
    """The losing side of cross-host claim competition does not launch."""

    def fake_submit(request: ProcSubmitRequest) -> Proc:
        raise AssertionError("must not submit without a launch permit")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        publish_claim=lambda _p, _r: _no_permit("existing_published_claim"),
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(_zombie_row()),
        submit_proc=fake_submit,
    )
    assert result.outcome == OUTCOME_ABORTED
    assert result.reason == "no_launch_permit:existing_published_claim"
    assert result.proc is None


def test_submit_failed_publish_never_submits(fake_claim_key: None) -> None:
    def fake_submit(request: ProcSubmitRequest) -> Proc:
        raise AssertionError("a failed publish must not submit")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        publish_claim=lambda _p, _r: _no_permit("publish_unconfirmed"),
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(_zombie_row()),
        submit_proc=fake_submit,
    )
    assert result.outcome == OUTCOME_ABORTED
    assert result.proc is None


def test_submit_replays_active_proc_without_submit(
    fake_claim_key: None,
) -> None:
    """Crash after reservation, restart after ack, and lost ack with a live
    row all resume the same reservation instead of minting a new proc."""
    claim = _claim()
    live = _proc(claim.proc_id, "running")

    def fake_submit(request: ProcSubmitRequest) -> Proc:
        raise AssertionError("an active row must replay, never resubmit")

    for status in ("pending", "running", "settling"):
        result = submit_recovery_launch(
            PROJECT,
            EPIC,
            close_token=TOKEN,
            publish_claim=lambda _p, _r: _permit(claim),
            lookup_proc=lambda _proc_id, _status=status: _proc(claim.proc_id, _status),
            load_report=lambda _project: (_ for _ in ()).throw(
                AssertionError("guard must not run before the replay check")
            ),
            submit_proc=fake_submit,
        )
        assert result.outcome == OUTCOME_REPLAYED
        assert result.proc is not None
        assert result.proc.status == status
    assert live.proc_id == claim.proc_id


def test_submit_consumes_terminal_proc_without_relaunch(
    fake_claim_key: None,
) -> None:
    """Repeated calls after a completed or failed proc never spawn again."""
    claim = _claim()

    def fake_submit(request: ProcSubmitRequest) -> Proc:
        raise AssertionError("a consumed event must never relaunch")

    for status in ("success", "error", "killed"):
        result = submit_recovery_launch(
            PROJECT,
            EPIC,
            close_token=TOKEN,
            publish_claim=lambda _p, _r: _permit(claim),
            lookup_proc=lambda _proc_id, _status=status: _proc(claim.proc_id, _status),
            load_report=lambda _project: (_ for _ in ()).throw(
                AssertionError("guard must not run for a consumed event")
            ),
            submit_proc=fake_submit,
        )
        assert result.outcome == OUTCOME_CONSUMED
        assert result.proc is not None
        assert result.proc.status == status


def test_submit_aborts_when_child_reopened_after_scheduling(
    fake_claim_key: None,
) -> None:
    """A child reopened between scan and execution aborts before submission."""
    claim = _claim()

    def fake_submit(request: ProcSubmitRequest) -> Proc:
        raise AssertionError("a reopened epic must not submit")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        publish_claim=lambda _p, _r: _permit(claim),
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(_zombie_row(state="open", eligible=False)),
        submit_proc=fake_submit,
    )
    assert result.outcome == OUTCOME_ABORTED
    assert result.reason.startswith("guard_refused:")
    assert result.proc is None


def test_submit_aborts_when_close_token_superseded(
    fake_claim_key: None,
) -> None:
    claim = _claim()

    def fake_submit(request: ProcSubmitRequest) -> Proc:
        raise AssertionError("a superseded token must not submit")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        publish_claim=lambda _p, _r: _permit(claim),
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(_zombie_row(token=OTHER_TOKEN)),
        submit_proc=fake_submit,
    )
    assert result.outcome == OUTCOME_ABORTED
    assert "close token changed" in (result.diagnostic or "")
    assert result.proc is None


def test_submit_aborts_on_unknown_evidence(fake_claim_key: None) -> None:
    claim = _claim()

    def fake_submit(request: ProcSubmitRequest) -> Proc:
        raise AssertionError("unknown evidence must not submit")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        publish_claim=lambda _p, _r: _permit(claim),
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(failed=True, reason="store unreadable"),
        submit_proc=fake_submit,
    )
    assert result.outcome == OUTCOME_ABORTED
    assert result.proc is None


def test_submit_conflict_rereads_the_winner(fake_claim_key: None) -> None:
    """Concurrent local submitters share one proc: the loser replays."""
    claim = _claim()
    winner = _proc(claim.proc_id, "pending")
    seen: list[str] = []

    def conflict_then_winner(request: ProcSubmitRequest) -> Proc:
        seen.append(request.proc_id)
        raise RuntimeError("active concurrency key overlaps")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        publish_claim=lambda _p, _r: _permit(claim),
        lookup_proc=lambda proc_id: winner if seen else None,
        load_report=lambda _project: _report(_zombie_row()),
        submit_proc=conflict_then_winner,
    )
    assert result.outcome == OUTCOME_REPLAYED
    assert result.proc == winner
    assert seen == [claim.proc_id]


def test_submit_conflict_without_winner_aborts(fake_claim_key: None) -> None:
    claim = _claim()

    def failing_submit(request: ProcSubmitRequest) -> Proc:
        raise RuntimeError("store unavailable")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        publish_claim=lambda _p, _r: _permit(claim),
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(_zombie_row()),
        submit_proc=failing_submit,
    )
    assert result.outcome == OUTCOME_ABORTED
    assert result.reason.startswith("submit_conflict:")
    assert result.proc is None


def test_in_store_entry_forwards_seams_and_submits(
    fake_claim_key: None, tmp_path: Path
) -> None:
    """The store-level entry drives crash-replay seams end to end."""
    claim = _claim()
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    seen: dict[str, Any] = {}

    def fake_publish(
        path: Path, request: dict[str, Any], **kwargs: Any
    ) -> RecoveryPublicationResult:
        seen["path"] = path
        seen["kwargs"] = kwargs
        return _permit(claim)

    submitted: list[ProcSubmitRequest] = []

    result = submit_recovery_launch_in_store(
        beads_dir,
        project=PROJECT,
        epic_id=EPIC,
        close_token=TOKEN,
        owner_machine="athena",
        publish_claim=fake_publish,
        refresh=lambda _path: seen.setdefault("refresh", True),
        commit=lambda _path, _message: True,
        push=lambda _path: None,
        replay=lambda _path: None,
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(_zombie_row()),
        submit_proc=lambda request: (
            submitted.append(request) or _proc(claim.proc_id, "pending")
        ),
    )
    assert result.outcome == OUTCOME_SUBMITTED
    assert seen["path"] == beads_dir
    assert set(seen["kwargs"]) == {"refresh", "commit", "push", "replay"}
    assert len(submitted) == 1


def test_in_store_entry_refuses_without_permit(
    fake_claim_key: None, tmp_path: Path
) -> None:
    """Corrupt claims surface as no-permit and never submit."""

    def fake_publish(
        path: Path, request: dict[str, Any], **kwargs: Any
    ) -> RecoveryPublicationResult:
        return RecoveryPublicationResult(
            launch_permit=False,
            reason="claim_refused",
            published=False,
            local_winner=False,
            diagnostic="recovery claims/abc.json is not valid JSON",
        )

    def fake_submit(request: ProcSubmitRequest) -> Proc:
        raise AssertionError("a corrupt claim must not submit")

    result = submit_recovery_launch_in_store(
        tmp_path,
        project=PROJECT,
        epic_id=EPIC,
        close_token=TOKEN,
        publish_claim=fake_publish,
        lookup_proc=lambda _proc_id: None,
        load_report=lambda _project: _report(_zombie_row()),
        submit_proc=fake_submit,
    )
    assert result.outcome == OUTCOME_ABORTED
    assert result.reason == "no_launch_permit:claim_refused"
    assert result.proc is None


def test_concurrent_local_submitters_share_one_proc(
    fake_claim_key: None,
) -> None:
    """Two racing submitters end up on one proc, never two launches."""
    import threading

    claim = _claim()
    store: dict[str, Proc] = {}
    lock = threading.Lock()
    launches = {"count": 0}

    def racing_submit(request: ProcSubmitRequest) -> Proc:
        with lock:
            assert request.proc_id is not None
            existing = store.get(request.proc_id)
            if existing is not None:
                return existing
            launches["count"] += 1
            proc = _proc(request.proc_id, "pending")
            store[request.proc_id] = proc
            return proc

    def racing_lookup(proc_id: str) -> Proc | None:
        with lock:
            return store.get(proc_id)

    results: list[Any] = []

    def run() -> None:
        results.append(
            submit_recovery_launch(
                PROJECT,
                EPIC,
                close_token=TOKEN,
                publish_claim=lambda _p, _r: _permit(claim),
                lookup_proc=racing_lookup,
                load_report=lambda _project: _report(_zombie_row()),
                submit_proc=racing_submit,
            )
        )

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert launches["count"] == 1
    assert {result.outcome for result in results} <= {
        OUTCOME_REPLAYED,
        OUTCOME_SUBMITTED,
    }
    assert {result.proc_id for result in results} == {claim.proc_id}
    assert list(store) == [claim.proc_id]


def test_default_submit_uses_operational_lease_with_axe_origin(
    fake_claim_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default submitter leases the project and submits through it."""
    from sase.bead import recovery_submit

    captured: dict[str, Any] = {}
    sentinel = object()

    def fake_acquire(project: str, *, workflow: str, holder: str, **kwargs: Any) -> Any:
        captured["project"] = project
        captured["workflow"] = workflow
        captured["holder"] = holder
        return sentinel

    def fake_submit_via_lease(request: ProcSubmitRequest, lease: Any) -> Proc:
        captured["request"] = request
        captured["lease"] = lease
        return _proc(request.proc_id or "missing", "pending")

    monkeypatch.setattr(
        "sase.workspace_provider.lease.acquire_operational_lease", fake_acquire
    )
    monkeypatch.setattr(
        "sase.workspace_provider.lease.submit_via_lease", fake_submit_via_lease
    )
    request = recovery_proc_request(project=PROJECT, epic_id=EPIC, close_token=TOKEN)
    proc = recovery_submit._lease_and_submit(request)
    assert captured["project"] == PROJECT
    assert captured["workflow"] == "epic-recovery"
    assert captured["holder"] == "epic-recovery"
    assert captured["lease"] is sentinel
    assert captured["request"] is request
    assert proc.proc_id == request.proc_id


def test_unsupported_core_binding_aborts(
    fake_claim_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel predating the claim-key contract never publishes or submits."""

    def missing_binding(project_id: str, epic_id: str, close_token: str) -> str:
        raise RuntimeError("sase_core_rs does not expose bead_recovery_claim_key")

    monkeypatch.setattr("sase.bead.recovery_submit.recovery_claim_key", missing_binding)

    def fake_publish(project: str, request: dict[str, Any]) -> Any:
        raise AssertionError("must not publish without a claim key")

    result = submit_recovery_launch(
        PROJECT,
        EPIC,
        close_token=TOKEN,
        publish_claim=fake_publish,
        lookup_proc=lambda _proc_id: (_ for _ in ()).throw(
            AssertionError("must not look up without an identity")
        ),
    )
    assert result.outcome == OUTCOME_ABORTED
    assert result.reason == "unsupported_core_binding"
    assert result.proc is None
