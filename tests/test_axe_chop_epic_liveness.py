"""Scheduler coverage for bounded, restart-safe epic recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any

import pytest

from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot
from sase.bead.recovery_submit import (
    OUTCOME_CONSUMED,
    OUTCOME_SUBMITTED,
    RecoverySubmission,
)
from sase.bead.zombie import ZombieReport
from sase.chops.sdk import ChopResultBuilder
from sase.core.recovery_facade import (
    RECOVERY_STATE_ABSENT,
    RECOVERY_STATE_ARMED,
    RecoveryActivation,
    RecoveryActivationInspect,
    RecoveryStoreInspect,
)
from sase.core.zombie_facade import ZombieEvaluationReport, ZombieVerdict
from sase.scripts import sase_chop_epic_liveness as job


def _snapshot(project: str, root: Path) -> BeadStoreSnapshot:
    return BeadStoreSnapshot(
        origin=BeadStoreOrigin(
            project_key=project,
            project_label=project.title(),
            primary_workspace=root,
            beads_dir=root,
        ),
        store_key=project,
        issue_ids=frozenset(),
        issue_prefix=project,
        project_refs=frozenset({project}),
    )


def _runtime(state_dir: Path) -> Any:
    class Log:
        lines: list[str] = []

        def info(self, message: str) -> None:
            self.lines.append(message)

        def warning(self, message: str) -> None:
            self.lines.append(message)

    class Runtime:
        context = SimpleNamespace(state_dir=str(state_dir), dry_run=False)
        log = Log()

        @staticmethod
        def emit_summary(fields: dict[str, int], *, reason: str | None = None):
            return ChopResultBuilder(counters=dict(fields), reason=reason)

    return Runtime()


def _row(
    plan_id: str,
    *,
    close_at: float,
    close_token: str | None = None,
    tier: str | None = "epic",
    state: str = "zombie",
    eligible: bool = True,
) -> ZombieVerdict:
    return ZombieVerdict(
        plan_id=plan_id,
        title=f"Plan {plan_id}",
        tier=tier,
        state=state,
        zombie=state == "zombie",
        recovery_eligible=eligible,
        close_token=close_token or f"{plan_id}:close",
        latest_descendant_closed_at=datetime.fromtimestamp(
            close_at, tz=UTC
        ).isoformat(),
        latest_descendant_close_event_id="close",
        tree_complete=True,
    )


def _report(
    project: str,
    *rows: ZombieVerdict,
    generated_at: float,
    latest_owner_terminal_at: dict[str, float] | None = None,
) -> ZombieReport:
    return ZombieReport(
        report=ZombieEvaluationReport(rows=tuple(rows)),
        project=project,
        titles={},
        generated_at=generated_at,
        latest_owner_terminal_at=latest_owner_terminal_at or {},
    )


def _inspection(
    project: str,
    activation: RecoveryActivation | None,
    *,
    state: str | None = None,
    claims: tuple = (),
) -> RecoveryStoreInspect:
    return RecoveryStoreInspect(
        activation=RecoveryActivationInspect(
            project_id=project,
            state=state
            or (RECOVERY_STATE_ARMED if activation else RECOVERY_STATE_ABSENT),
            recovery_enabled=activation is not None,
            activation=activation,
        ),
        claims=claims,
    )


def _submitted(proc_id: str, outcome: str = OUTCOME_SUBMITTED) -> RecoverySubmission:
    return RecoverySubmission(outcome=outcome, reason=outcome, proc_id=proc_id)


def test_activation_pass_is_report_only_even_when_another_project_is_armed(
    tmp_path: Path, monkeypatch
) -> None:
    snapshots = [
        _snapshot("alpha", tmp_path / "alpha"),
        _snapshot("beta", tmp_path / "beta"),
    ]
    activation = RecoveryActivation("beta", "1970-01-01T00:16:40+00:00", 1)
    states = {"alpha": None, "beta": activation}
    armed: list[str] = []
    submitted: list[str] = []

    monkeypatch.setattr(job, "enabled_project_store_snapshots", lambda: snapshots)
    monkeypatch.setattr(
        job,
        "inspect_recovery_store",
        lambda _path, project: _inspection(project, states[project]),
    )

    def arm(project: str, *, now: float):
        armed.append(project)
        states[project] = RecoveryActivation(
            project,
            datetime.fromtimestamp(now, tz=UTC).isoformat(),
            1,
        )
        return SimpleNamespace(
            launch_permit=True,
            activation=states[project],
            published=True,
            local_winner=True,
        )

    monkeypatch.setattr(job, "_arm_project", arm)
    monkeypatch.setattr(
        job,
        "load_zombie_report",
        lambda project: _report(
            project,
            _row(f"{project}-epic", close_at=900),
            generated_at=2_000,
        ),
    )
    monkeypatch.setattr(
        job,
        "submit_recovery_launch",
        lambda project, *_args, **_kwargs: (
            submitted.append(project) or _submitted(project)
        ),
    )
    monkeypatch.setattr(job.time, "time", lambda: 2_000)

    result = job._run(_runtime(tmp_path / "state"))

    assert armed == ["alpha"]
    assert submitted == []
    assert result.reason == "activation_armed"
    assert result.counters["armed"] == 1


def test_fake_clock_arms_waits_through_grace_and_replays_after_restart(
    tmp_path: Path, monkeypatch
) -> None:
    project = "demo"
    snapshots = [_snapshot(project, tmp_path / project)]
    current = {"time": 1_000.0, "activation": None, "close_at": 1_010.0}
    launch_outcomes = [OUTCOME_SUBMITTED, OUTCOME_CONSUMED]
    submissions: list[str] = []

    monkeypatch.setattr(job, "enabled_project_store_snapshots", lambda: snapshots)

    def inspect(_path: str, project_id: str) -> RecoveryStoreInspect:
        return _inspection(project_id, current["activation"])

    monkeypatch.setattr(job, "inspect_recovery_store", inspect)

    def arm(project_id: str, *, now: float):
        activation = RecoveryActivation(
            project_id,
            datetime.fromtimestamp(now, tz=UTC).isoformat(timespec="seconds"),
            1,
        )
        current["activation"] = activation
        return SimpleNamespace(
            launch_permit=True,
            activation=activation,
            published=True,
            local_winner=True,
        )

    monkeypatch.setattr(job, "_arm_project", arm)
    monkeypatch.setattr(
        job,
        "load_zombie_report",
        lambda key: _report(
            key,
            _row("demo-epic", close_at=current["close_at"]),
            generated_at=current["time"],
        ),
    )

    def submit(project_id: str, epic_id: str, **_kwargs: Any) -> RecoverySubmission:
        submissions.append(f"{project_id}/{epic_id}")
        return _submitted(epic_id, launch_outcomes.pop(0))

    monkeypatch.setattr(job, "submit_recovery_launch", submit)
    monkeypatch.setattr(job.time, "time", lambda: current["time"])
    runtime = _runtime(tmp_path / "state")

    armed = job._run(runtime)
    assert armed.reason == "activation_armed"
    assert not submissions

    current["time"] = 1_050.0
    grace = job._run(_runtime(tmp_path / "state"))
    assert grace.counters["grace"] == 1
    assert not submissions

    current["time"] = 1_131.0
    submitted = job._run(_runtime(tmp_path / "state"))
    assert submitted.counters["submitted"] == 1
    assert submissions == ["demo/demo-epic"]

    restarted = job._run(_runtime(tmp_path / "state"))
    assert restarted.counters["consumed"] == 1
    assert restarted.counters["submitted"] == 0
    assert submissions == ["demo/demo-epic", "demo/demo-epic"]


def test_owner_terminal_evidence_restarts_the_settlement_grace(
    tmp_path: Path, monkeypatch
) -> None:
    snapshots = [_snapshot("demo", tmp_path / "demo")]
    activation = RecoveryActivation("demo", "1970-01-01T00:16:40+00:00", 1)
    submitted: list[str] = []
    monkeypatch.setattr(job, "enabled_project_store_snapshots", lambda: snapshots)
    monkeypatch.setattr(
        job, "inspect_recovery_store", lambda _path, key: _inspection(key, activation)
    )
    monkeypatch.setattr(
        job,
        "load_zombie_report",
        lambda key: _report(
            key,
            _row("demo-epic", close_at=1_100),
            generated_at=1_200,
            latest_owner_terminal_at={"demo-epic": 1_190},
        ),
    )
    monkeypatch.setattr(
        job,
        "submit_recovery_launch",
        lambda _project, epic_id, **_kwargs: (
            submitted.append(epic_id) or _submitted(epic_id)
        ),
    )
    monkeypatch.setattr(job.time, "time", lambda: 1_200)

    result = job._run(_runtime(tmp_path / "state"))

    assert result.counters["grace"] == 1
    assert not submitted


def test_activation_is_not_rearmed_when_claims_exist_without_a_cutoff(
    tmp_path: Path, monkeypatch
) -> None:
    snapshot = _snapshot("demo", tmp_path / "demo")
    armed: list[str] = []
    inspected = _inspection("demo", None, claims=(object(),))
    monkeypatch.setattr(job, "enabled_project_store_snapshots", lambda: [snapshot])
    monkeypatch.setattr(job, "inspect_recovery_store", lambda *_args: inspected)
    monkeypatch.setattr(
        job,
        "_arm_project",
        lambda project, **_kwargs: (
            armed.append(project)
            or pytest.fail("existing claims must prevent re-arming")
        ),
    )
    monkeypatch.setattr(job.time, "time", lambda: 2_000)

    result = job._run(_runtime(tmp_path / "state"))

    assert result.counters["failed"] == 1
    assert not armed


def test_project_and_candidate_cursors_survive_budget_cutoff_and_restart(
    tmp_path: Path, monkeypatch
) -> None:
    snapshots = [
        _snapshot("alpha", tmp_path / "alpha"),
        _snapshot("beta", tmp_path / "beta"),
    ]
    activation = {
        project: RecoveryActivation(project, "1970-01-01T00:00:00+00:00", 1)
        for project in ("alpha", "beta")
    }
    monotonic = {"now": 0.0}
    reported: list[str] = []
    monkeypatch.setattr(job, "enabled_project_store_snapshots", lambda: snapshots)
    monkeypatch.setattr(
        job,
        "inspect_recovery_store",
        lambda _path, project: _inspection(project, activation[project]),
    )
    monkeypatch.setattr(job.time, "monotonic", lambda: monotonic["now"])
    monkeypatch.setattr(job.time, "time", lambda: 2_000)

    def load(project: str) -> ZombieReport:
        reported.append(project)
        if project == "alpha" and monotonic["now"] == 0:
            monotonic["now"] = 31.0
        return _report(
            project,
            _row(f"{project}-owned", close_at=900, state="owned", eligible=False),
            generated_at=2_000,
        )

    monkeypatch.setattr(job, "load_zombie_report", load)

    first = job._run(_runtime(tmp_path / "state"))
    assert first.reason == "budget_exhausted"
    assert reported == ["alpha"]

    monotonic["now"] = 0.0
    job._run(_runtime(tmp_path / "state"))
    assert reported[1:] == ["beta", "alpha"]


def test_candidate_cursor_advances_to_the_next_epic_after_restart(
    tmp_path: Path, monkeypatch
) -> None:
    snapshot = _snapshot("demo", tmp_path / "demo")
    activation = RecoveryActivation("demo", "1970-01-01T00:00:00+00:00", 1)
    submitted: list[str] = []
    monkeypatch.setattr(job, "enabled_project_store_snapshots", lambda: [snapshot])
    monkeypatch.setattr(
        job, "inspect_recovery_store", lambda _path, key: _inspection(key, activation)
    )
    monkeypatch.setattr(
        job,
        "load_zombie_report",
        lambda project: _report(
            project,
            _row("demo-epic-a", close_at=900),
            _row("demo-epic-b", close_at=900),
            generated_at=2_000,
        ),
    )
    monkeypatch.setattr(
        job,
        "submit_recovery_launch",
        lambda _project, epic_id, **_kwargs: (
            submitted.append(epic_id) or _submitted(epic_id)
        ),
    )
    monkeypatch.setattr(job.time, "time", lambda: 2_000)

    first = job._run(_runtime(tmp_path / "state"))
    second = job._run(_runtime(tmp_path / "state"))

    assert first.counters["submitted"] == 1
    assert second.counters["submitted"] == 1
    assert submitted == ["demo-epic-a", "demo-epic-b"]


def test_one_new_submission_per_pass_and_projects_rotate_fairly(
    tmp_path: Path, monkeypatch
) -> None:
    snapshots = [
        _snapshot("alpha", tmp_path / "alpha"),
        _snapshot("beta", tmp_path / "beta"),
    ]
    activations = {
        project: RecoveryActivation(project, "1970-01-01T00:00:00+00:00", 1)
        for project in ("alpha", "beta")
    }
    submissions: list[str] = []
    monkeypatch.setattr(job, "enabled_project_store_snapshots", lambda: snapshots)
    monkeypatch.setattr(
        job,
        "inspect_recovery_store",
        lambda _path, project: _inspection(project, activations[project]),
    )
    monkeypatch.setattr(
        job,
        "load_zombie_report",
        lambda project: _report(
            project,
            _row(f"{project}-epic", close_at=900),
            generated_at=2_000,
        ),
    )
    monkeypatch.setattr(
        job,
        "submit_recovery_launch",
        lambda project, epic_id, **_kwargs: (
            submissions.append(project) or _submitted(epic_id)
        ),
    )
    monkeypatch.setattr(job.time, "time", lambda: 2_000)

    first = job._run(_runtime(tmp_path / "state"))
    second = job._run(_runtime(tmp_path / "state"))

    assert first.counters["submitted"] == 1
    assert second.counters["submitted"] == 1
    assert submissions == ["alpha", "beta"]


def test_overlap_skips_the_second_tick_while_the_first_owns_the_job_lock(
    tmp_path: Path, monkeypatch
) -> None:
    snapshots = [_snapshot("demo", tmp_path / "demo")]
    activation = RecoveryActivation("demo", "1970-01-01T00:00:00+00:00", 1)
    entered = Event()
    release = Event()
    submissions: list[str] = []
    monkeypatch.setattr(job, "enabled_project_store_snapshots", lambda: snapshots)
    monkeypatch.setattr(
        job, "inspect_recovery_store", lambda _path, key: _inspection(key, activation)
    )
    monkeypatch.setattr(
        job,
        "load_zombie_report",
        lambda project: _report(
            project,
            _row("demo-epic", close_at=900),
            generated_at=2_000,
        ),
    )

    def submit(_project: str, epic_id: str, **_kwargs: Any) -> RecoverySubmission:
        submissions.append(epic_id)
        entered.set()
        release.wait(timeout=5)
        return _submitted(epic_id)

    monkeypatch.setattr(job, "submit_recovery_launch", submit)
    monkeypatch.setattr(job.time, "time", lambda: 2_000)
    runtime = _runtime(tmp_path / "state")
    first_result: list[ChopResultBuilder] = []
    thread = Thread(target=lambda: first_result.append(job._run(runtime)))
    thread.start()
    assert entered.wait(timeout=5)
    second = job._run(_runtime(tmp_path / "state"))
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert first_result[0].counters["submitted"] == 1
    assert second.reason == "already_running"
    assert submissions == ["demo-epic"]
