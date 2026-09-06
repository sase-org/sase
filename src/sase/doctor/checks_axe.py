"""AXE chop checks for ``sase doctor``."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from sase.axe.chop_doctor import (
    ChopCheck,
    build_chop_doctor_report,
    chop_check_to_dict,
)
from sase.axe.desired_state import read_desired_state
from sase.axe._process_probe import probe_orchestrator
from sase.axe.systemd_scope import unsafe_axe_systemd_scope
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
            title="AXE desired runtime health",
            runner=_check_axe_health,
        ),
        CheckSpec(
            id="axe.chops",
            group="axe",
            title="AXE chop diagnostics",
            runner=lambda: _check_axe_chops(context),
        ),
        CheckSpec(
            id="axe.systemd_scope",
            group="axe",
            title="AXE systemd scope isolation",
            runner=_check_axe_systemd_scope,
        ),
    )


def _check_axe_health() -> DiagnosticCheck:
    """Flag a requested-running axe whose orchestrator is down."""
    desired = read_desired_state()
    pid = probe_orchestrator(cleanup=False).running_pid
    if desired is not None and desired.state == "running" and pid is None:
        return DiagnosticCheck(
            id="axe.health",
            group="axe",
            status="WARN",
            title="AXE desired runtime health",
            summary="axe is desired running, but its orchestrator is down",
            details=(
                f"Running was requested by {desired.source} at {desired.timestamp}.",
            ),
            next_steps=("Run `sase axe ensure`.",),
            data={
                "desired_state": desired.state,
                "desired_state_source": desired.source,
                "desired_state_timestamp": desired.timestamp,
                "orchestrator_pid": None,
            },
        )

    desired_value = desired.state if desired is not None else None
    if pid is not None:
        summary = f"axe orchestrator is running (pid {pid})"
    elif desired_value == "stopped":
        summary = "axe is explicitly stopped"
    else:
        summary = "no axe desired-state marker or live orchestrator was found"
    return DiagnosticCheck(
        id="axe.health",
        group="axe",
        status="OK",
        title="AXE desired runtime health",
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


def _check_axe_systemd_scope() -> DiagnosticCheck:
    """Warn when the live orchestrator will die with a launching session."""
    pid = probe_orchestrator(cleanup=False).running_pid
    scope = unsafe_axe_systemd_scope(pid) if pid is not None else None
    if scope is None:
        return DiagnosticCheck(
            id="axe.systemd_scope",
            group="axe",
            status="OK",
            title="AXE systemd scope isolation",
            summary="axe has no detectable session-tied systemd scope",
            data={"orchestrator_pid": pid, "systemd_scope": None},
        )

    return DiagnosticCheck(
        id="axe.systemd_scope",
        group="axe",
        status="WARN",
        title="AXE systemd scope isolation",
        summary="axe orchestrator is attached to a session-tied systemd scope",
        details=(
            f"PID {pid} is in {scope} and will be killed when its launching "
            "pane or session closes.",
        ),
        next_steps=("Run `sase axe restart`.",),
        data={"orchestrator_pid": pid, "systemd_scope": scope},
    )


def _check_axe_chops(context: DoctorContext) -> DiagnosticCheck:
    """Adapt ``sase axe chop doctor`` into one shared diagnostic check."""
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
        summary = f"chop diagnostics passed: {len(checks)} check(s)"
    else:
        summary = (
            f"chop diagnostics reported {counts['ERROR']} error(s), "
            f"{counts['WARN']} warning(s)"
        )

    return DiagnosticCheck(
        id="axe.chops",
        group="axe",
        status=status,
        title="AXE chop diagnostics",
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
            "configured_chop_count": len(inventory.configured_chops),
            "available_chop_count": len(inventory.available_scripts),
            "available_unconfigured_count": len(inventory.available_unconfigured),
            "checks": [chop_check_to_dict(check) for check in _bounded_checks(checks)],
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
