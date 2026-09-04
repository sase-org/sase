"""Initialization planner checks for ``sase doctor``."""

from __future__ import annotations

import argparse
from typing import Any, TYPE_CHECKING

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.main.init_plan import InitPlan, serialize_init_plan
from sase.main.init_registry import iter_init_command_specs

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_PRETTIER_MISSING_SKILL_DRIFT_NOTE = (
    "stale counts may be inflated: prettier missing; generated skill files render "
    "without deployed formatting"
)


def check_config_init(context: DoctorContext) -> DiagnosticCheck:
    """Run registered read-only init planners and summarize drift."""
    args = argparse.Namespace(
        command="doctor",
        init_subcommand=None,
        path=str(context.cwd),
        check=True,
        no_commit=True,
        no_push=True,
        no_apply=True,
        dry_run=True,
        force=False,
        provider=None,
    )
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []
    action_count = 0
    prettier_missing_skill_drift = False

    for spec in iter_init_command_specs():
        try:
            plan = spec.plan(args)
        except Exception as exc:  # noqa: BLE001 - doctor reports planner failures.
            message = f"{spec.name}: {type(exc).__name__}: {exc}"
            blockers.append(message)
            rows.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "summary": "planner failed",
                    "actions": [],
                    "warnings": [],
                    "blockers": [message],
                }
            )
            continue

        row = serialize_init_plan(plan, max_actions=MAX_DETAIL_ROWS)
        rows.append(row)
        action_count += int(row["action_count"])
        warnings.extend(str(item) for item in plan.warnings)
        if _plan_has_prettier_missing_skill_drift(plan):
            prettier_missing_skill_drift = True
        blockers.extend(str(item) for item in plan.blockers)
        if plan.actions:
            problems.append(f"{plan.command}: {plan.summary}")

    status: CheckStatus = (
        "ERROR" if blockers else "WARN" if problems or warnings else "OK"
    )
    summary = _init_summary(
        planner_count=len(rows),
        action_count=action_count,
        warning_count=len(warnings),
        blocker_count=len(blockers),
    )
    details = [
        *blockers,
        *([_PRETTIER_MISSING_SKILL_DRIFT_NOTE] if prettier_missing_skill_drift else []),
        *warnings,
        *problems,
    ]
    next_steps = []
    if blockers or warnings or problems:
        next_steps.append("Run `sase init --check` for the full initialization plan.")
    for row in rows:
        if row["actions"] or row["blockers"]:
            next_steps.append(f"Run `sase init {row['name']} --check`.")

    return DiagnosticCheck(
        id="config.init",
        group="config",
        status=status,
        title="Initialization planners",
        summary=summary,
        details=tuple(details[:MAX_DETAIL_ROWS]),
        next_steps=tuple(dict.fromkeys(next_steps)),
        data={
            "planners": rows,
            "action_count": action_count,
            "warning_count": len(warnings),
            "blocker_count": len(blockers),
            "prettier_missing_skill_drift_note": prettier_missing_skill_drift,
        },
    )


def _plan_has_prettier_missing_skill_drift(plan: InitPlan) -> bool:
    if plan.command != "skills" or not plan.actions:
        return False
    return any(
        "prettier not found" in str(warning).lower() for warning in plan.warnings
    )


def _init_summary(
    *,
    planner_count: int,
    action_count: int,
    warning_count: int,
    blocker_count: int,
) -> str:
    if blocker_count:
        return f"{blocker_count} init blocker(s) found"
    if action_count or warning_count:
        return (
            f"{action_count} planned init action(s), "
            f"{warning_count} warning(s) across {planner_count} planners"
        )
    return f"{planner_count} init planners current"
