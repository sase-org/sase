"""Per-candidate eligibility coverage for the ``epic_liveness`` AXE job.

These complement the pass-level scheduler tests with the rollout and
claim-ownership invariants: historical closes stay report-only, a later
reclose earns its own token, unknown/unsupported rows never launch, a claim
owned by another host is never transferred, a consumed token skips the
publish round trip, and a failed submission is counted as a failure.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.bead.recovery_submit import (
    OUTCOME_ABORTED,
    REASON_SUBMIT_CONFLICT,
    RecoverySubmission,
)
from sase.core.recovery_facade import (
    RECOVERY_STATE_EXISTING,
    RecoveryActivation,
    RecoveryClaim,
    RecoveryClaimInspect,
    RecoveryStoreInspect,
)
from sase.core.zombie_facade import ZombieVerdict
from sase.procs.models import Proc
from sase.scripts import sase_chop_epic_liveness as job
from tests._epic_liveness_helpers import (
    make_inspection,
    make_report,
    make_row,
    make_runtime,
    make_snapshot,
    make_submission,
)

PROJECT = "demo"
CUTOFF = 1_000.0
CUTOFF_ISO = "1970-01-01T00:16:40+00:00"
NOW = 2_000.0


def _claim(
    epic_id: str, close_token: str, *, owner: str = "athena"
) -> RecoveryClaimInspect:
    return RecoveryClaimInspect(
        claim_key=f"key-{epic_id}-{close_token}",
        project_id=PROJECT,
        epic_id=epic_id,
        close_token=close_token,
        state=RECOVERY_STATE_EXISTING,
        claim=RecoveryClaim(
            project_id=PROJECT,
            epic_id=epic_id,
            close_token=close_token,
            owner_machine=owner,
            proc_id=f"epic-recovery-{epic_id}-{close_token}",
            request_fingerprint=f"epic-recovery:{epic_id}-{close_token}",
            activation_generation=1,
            created_at=CUTOFF_ISO,
        ),
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
        created_at=CUTOFF_ISO,
        log_path="/tmp/recovery.log",
    )


def _run_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *rows: ZombieVerdict,
    claims: tuple[RecoveryClaimInspect, ...] = (),
    procs: dict[str, Proc] | None = None,
    submit_outcome: RecoverySubmission | None = None,
) -> tuple[Any, list[tuple[str, str]]]:
    """Run one armed pass over *rows*, returning the result and submissions."""

    activation = RecoveryActivation(PROJECT, CUTOFF_ISO, 1)
    inspected: RecoveryStoreInspect = make_inspection(
        PROJECT, activation, claims=claims
    )
    submissions: list[tuple[str, str]] = []
    monkeypatch.setattr(
        job,
        "enabled_project_store_snapshots",
        lambda: [make_snapshot(PROJECT, tmp_path / PROJECT)],
    )
    monkeypatch.setattr(job, "inspect_recovery_store", lambda *_args: inspected)
    monkeypatch.setattr(
        job, "_arm_project", lambda *_a, **_k: pytest.fail("already armed")
    )
    monkeypatch.setattr(
        job,
        "load_zombie_report",
        lambda key: make_report(key, *rows, generated_at=NOW),
    )
    monkeypatch.setattr(job, "default_owner_machine", lambda: "athena")
    monkeypatch.setattr(job, "get_proc", lambda proc_id: (procs or {}).get(proc_id))

    def submit(_project: str, epic_id: str, **kwargs: Any) -> RecoverySubmission:
        submissions.append((epic_id, kwargs["close_token"]))
        return submit_outcome or make_submission(epic_id)

    monkeypatch.setattr(job, "submit_recovery_launch", submit)
    monkeypatch.setattr(job.time, "time", lambda: NOW)
    return job._run(make_runtime(tmp_path / "state")), submissions


def test_pre_activation_and_equal_cutoff_closes_stay_historical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, submissions = _run_pass(
        tmp_path,
        monkeypatch,
        make_row("demo-before", close_at=CUTOFF - 1),
        make_row("demo-equal", close_at=CUTOFF),
    )

    assert submissions == []
    assert result.counters["historical"] == 2
    assert result.counters["submitted"] == 0


def test_reclose_after_a_consumed_token_earns_its_own_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-activation epic whose child recloses after the cutoff recovers once."""

    consumed = _claim("demo-epic", "demo-epic.1:evt-1")
    assert consumed.claim is not None
    result, submissions = _run_pass(
        tmp_path,
        monkeypatch,
        make_row("demo-epic", close_at=CUTOFF + 500, close_token="demo-epic.1:evt-2"),
        claims=(consumed,),
        procs={consumed.claim.proc_id: _proc(consumed.claim.proc_id, "error")},
    )

    assert submissions == [("demo-epic", "demo-epic.1:evt-2")]
    assert result.counters["submitted"] == 1


def test_unknown_and_unsupported_rows_never_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unknown = replace(
        make_row("demo-unknown", close_at=CUTOFF + 500, eligible=False),
        unknown_reason="session records unavailable",
    )
    result, submissions = _run_pass(
        tmp_path,
        monkeypatch,
        unknown,
        make_row("demo-tale", close_at=CUTOFF + 500, tier="tale"),
    )

    assert submissions == []
    assert result.counters["unknown"] == 1
    assert result.counters["deferred"] == 1
    assert result.counters["submitted"] == 0


def test_claim_owned_by_another_host_is_never_transferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "demo-epic.1:evt-2"
    result, submissions = _run_pass(
        tmp_path,
        monkeypatch,
        make_row("demo-epic", close_at=CUTOFF + 500, close_token=token),
        claims=(_claim("demo-epic", token, owner="apollo"),),
    )

    assert submissions == []
    assert result.counters["deferred"] == 1


def test_consumed_token_skips_the_publish_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "demo-epic.1:evt-2"
    claim = _claim("demo-epic", token)
    assert claim.claim is not None
    result, submissions = _run_pass(
        tmp_path,
        monkeypatch,
        make_row("demo-epic", close_at=CUTOFF + 500, close_token=token),
        claims=(claim,),
        procs={claim.claim.proc_id: _proc(claim.claim.proc_id, "done")},
    )

    assert submissions == []
    assert result.counters["consumed"] == 1
    assert result.counters["submitted"] == 0


def test_own_claim_without_a_proc_row_resumes_through_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash before reservation resumes the same claim on its owning host."""

    token = "demo-epic.1:evt-2"
    result, submissions = _run_pass(
        tmp_path,
        monkeypatch,
        make_row("demo-epic", close_at=CUTOFF + 500, close_token=token),
        claims=(_claim("demo-epic", token),),
    )

    assert submissions == [("demo-epic", token)]
    assert result.counters["submitted"] == 1


def test_failed_submission_counts_as_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, submissions = _run_pass(
        tmp_path,
        monkeypatch,
        make_row("demo-epic", close_at=CUTOFF + 500),
        submit_outcome=RecoverySubmission(
            outcome=OUTCOME_ABORTED,
            reason=f"{REASON_SUBMIT_CONFLICT}:lease allocation failed",
            proc_id="epic-recovery-demo-epic",
        ),
    )

    assert len(submissions) == 1
    assert result.counters["failed"] == 1
    assert result.counters["submitted"] == 0
    assert result.status == "check_error"
