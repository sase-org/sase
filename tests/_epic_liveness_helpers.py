"""Shared fixtures for the ``epic_liveness`` AXE job tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.bead.cross_project import BeadStoreOrigin, BeadStoreSnapshot
from sase.bead.recovery_submit import OUTCOME_SUBMITTED, RecoverySubmission
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


def make_snapshot(project: str, root: Path) -> BeadStoreSnapshot:
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


def make_runtime(state_dir: Path) -> Any:
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


def make_row(
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


def make_report(
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


def make_inspection(
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


def make_submission(
    proc_id: str, outcome: str = OUTCOME_SUBMITTED
) -> RecoverySubmission:
    return RecoverySubmission(outcome=outcome, reason=outcome, proc_id=proc_id)
