"""Plugin subsystem checks for ``sase doctor``."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.plugins.doctor import (
    DoctorCheck,
    build_plugin_doctor_report,
    doctor_check_to_dict,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def plugin_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default plugin check specs."""
    return (
        CheckSpec(
            id="plugins.doctor",
            group="plugins",
            title="Plugin diagnostics",
            runner=lambda: _check_plugins_doctor(context),
        ),
    )


def _check_plugins_doctor(context: DoctorContext) -> DiagnosticCheck:
    """Adapt ``sase plugin doctor`` into one shared diagnostic check."""
    report = build_plugin_doctor_report()
    counts = Counter(check.status for check in report.checks)
    problem_checks = tuple(check for check in report.checks if check.status != "OK")
    detail_checks = report.checks if context.verbose else problem_checks
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

    if report.status == "OK":
        summary = f"plugin doctor passed: {len(report.checks)} check(s)"
    else:
        summary = (
            f"plugin doctor reported {counts['ERROR']} error(s), "
            f"{counts['WARN']} warning(s), {counts['SKIP']} skipped"
        )

    return DiagnosticCheck(
        id="plugins.doctor",
        group="plugins",
        status=report.status,
        title="Plugin diagnostics",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "status": report.status,
            "counts": {
                "OK": counts["OK"],
                "WARN": counts["WARN"],
                "ERROR": counts["ERROR"],
                "SKIP": counts["SKIP"],
            },
            "check_count": len(report.checks),
            "problem_check_count": len(problem_checks),
            "plugin_distribution_count": len(report.plugin_inventory.distributions),
            "entry_point_count": len(report.plugin_inventory.entry_points),
            "configured_chop_count": len(report.chop_inventory.configured_chops),
            "available_chop_count": len(report.chop_inventory.available_scripts),
            "checks": [
                doctor_check_to_dict(check) for check in _bounded_checks(report.checks)
            ],
        },
    )


def _bounded_checks(checks: tuple[DoctorCheck, ...]) -> tuple[DoctorCheck, ...]:
    problems = tuple(check for check in checks if check.status != "OK")
    if problems:
        return problems[:_MAX_DETAIL_ROWS]
    return checks[:_MAX_DETAIL_ROWS]


__all__ = [
    "plugin_check_specs",
]
