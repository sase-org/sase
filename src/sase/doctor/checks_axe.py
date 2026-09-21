"""AXE chop checks for ``sase doctor``."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from sase.axe.chop_doctor import (
    ChopCheck,
    build_chop_doctor_report,
    chop_check_to_public_dict,
)
from sase.axe._process_probe import probe_orchestrator
from sase.axe._scheduler_desired_state import (
    scheduler_desired_running,
    scheduler_desired_state,
)
from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def axe_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default AXE check specs."""
    return (
        CheckSpec(
            id="axe.health",
            group="axe",
            title="Scheduler service proc health",
            runner=_check_axe_health,
        ),
        CheckSpec(
            id="axe.jobs",
            group="axe",
            title="AXE job diagnostics",
            aliases=("axe.chops",),
            runner=lambda: _check_axe_chops(context),
        ),
    )


def _check_axe_health() -> DiagnosticCheck:
    """Flag a scheduler the service host wants running whose orchestrator is down."""
    desired = scheduler_desired_state()
    pid = probe_orchestrator(cleanup=False).running_pid
    if scheduler_desired_running() and pid is None:
        return DiagnosticCheck(
            id="axe.health",
            group="axe",
            status="WARN",
            title="Scheduler service proc health",
            summary="scheduler is desired running, but its orchestrator is down",
            details=("The service host wants the scheduler service proc running.",),
            next_steps=(
                "Run `sase service status`.",
                "Run `sase scheduler start`.",
            ),
            data={
                "desired_state": desired.state if desired is not None else None,
                "desired_state_source": desired.source if desired is not None else None,
                "desired_state_timestamp": (
                    desired.timestamp if desired is not None else None
                ),
                "orchestrator_pid": None,
            },
        )

    desired_value = desired.state if desired is not None else None
    if pid is not None:
        summary = f"scheduler orchestrator is running (pid {pid})"
    elif desired_value == "stopped":
        summary = "scheduler is explicitly stopped"
    else:
        summary = "no scheduler desired state or live orchestrator was found"
    return DiagnosticCheck(
        id="axe.health",
        group="axe",
        status="OK",
        title="Scheduler service proc health",
        summary=summary,
        data={
            "desired_state": desired_value,
            "desired_state_source": desired.source if desired is not None else None,
            "desired_state_timestamp": (
                desired.timestamp if desired is not None else None
            ),
            "orchestrator_pid": pid,
        },
    )


def _check_axe_chops(context: DoctorContext) -> DiagnosticCheck:
    """Adapt ``sase axe job doctor`` into one shared diagnostic check."""
    report = build_chop_doctor_report()
    inventory = report.inventory
    checks = report.checks
    status = report.status
    counts = Counter(check.status for check in checks)
    problem_checks = tuple(check for check in checks if check.status != "OK")
    detail_checks = checks if context.verbose else problem_checks
    details = tuple(
        f"{check.status}: {check.id}: {check.summary}"
        for check in detail_checks[:_MAX_DETAIL_ROWS]
    )
    next_steps = tuple(
        dict.fromkeys(
            step
            for check in problem_checks
            for step in check.next_steps
            if step.strip()
        )
    )[:_MAX_DETAIL_ROWS]

    if status in {"OK", "SKIP"}:
        summary = f"job diagnostics passed: {len(checks)} check(s)"
    else:
        summary = (
            f"job diagnostics reported {counts['ERROR']} error(s), "
            f"{counts['WARN']} warning(s)"
        )

    return DiagnosticCheck(
        id="axe.jobs",
        group="axe",
        status=status,
        title="AXE job diagnostics",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "status": status,
            "counts": {
                "OK": counts["OK"],
                "WARN": counts["WARN"],
                "ERROR": counts["ERROR"],
                "SKIP": counts["SKIP"],
            },
            "check_count": len(checks),
            "problem_check_count": len(problem_checks),
            "configured_job_count": len(inventory.configured_chops),
            "available_job_count": len(inventory.available_scripts),
            "available_unconfigured_count": len(inventory.available_unconfigured),
            "checks": [
                chop_check_to_public_dict(check) for check in _bounded_checks(checks)
            ],
        },
    )


def _bounded_checks(checks: tuple[ChopCheck, ...]) -> tuple[ChopCheck, ...]:
    problems = tuple(check for check in checks if check.status != "OK")
    if problems:
        return problems[:_MAX_DETAIL_ROWS]
    return checks[:_MAX_DETAIL_ROWS]


__all__ = [
    "axe_check_specs",
]
