"""AXE chop checks for ``sase doctor``."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from sase.axe.chop_doctor import (
    ChopCheck,
    build_chop_doctor_report,
    chop_check_to_dict,
)
from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def axe_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default AXE check specs."""
    return (
        CheckSpec(
            id="axe.chops",
            group="axe",
            title="AXE chop diagnostics",
            runner=lambda: _check_axe_chops(context),
        ),
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
