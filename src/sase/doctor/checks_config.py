"""Configuration and SDD checks for ``sase doctor``."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.config.core import load_config_layers
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.main.init_plan import InitPlan
from sase.main.init_registry import iter_init_command_specs
from sase.sdd.links import resolve_sdd_root, validate_sdd_tree

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def config_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return Phase 2 config check specs."""
    return (
        CheckSpec(
            id="config.layers",
            group="config",
            title="Config layers",
            runner=_check_config_layers,
        ),
        CheckSpec(
            id="config.init",
            group="config",
            title="Initialization planners",
            runner=lambda: _check_config_init(context),
        ),
        CheckSpec(
            id="config.sdd",
            group="config",
            title="SDD validation",
            runner=lambda: _check_config_sdd(context),
        ),
    )


def _check_config_layers() -> DiagnosticCheck:
    """Report config layer visibility and parse/unsupported-key problems."""
    layers = load_config_layers()
    layer_rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for layer in layers:
        present = bool(layer.present) if layer.present is not None else layer.exists
        loaded = bool(layer.loaded)
        row = {
            "name": layer.name,
            "path": layer.path,
            "present": present,
            "loaded": loaded,
            "list_strategy": layer.list_strategy,
            "keys": list(layer.keys),
            "unsupported_keys": list(layer.unsupported_keys),
            "error": layer.error,
        }
        layer_rows.append(row)
        if layer.error:
            location = layer.path or layer.name
            problems.append(f"{location}: {layer.error}")
        if layer.unsupported_keys:
            location = layer.path or layer.name
            keys = ", ".join(layer.unsupported_keys)
            problems.append(f"{location}: unsupported keys ignored: {keys}")

    loaded_count = sum(1 for row in layer_rows if row["loaded"])
    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{loaded_count}/{len(layer_rows)} config layers loaded"
        if not problems
        else f"{len(problems)} config layer problem(s) found"
    )
    next_steps = []
    if problems:
        next_steps.append(
            "Fix the reported YAML/config keys, then rerun `sase config layers`."
        )

    return DiagnosticCheck(
        id="config.layers",
        group="config",
        status=status,
        title="Config layers",
        summary=summary,
        details=tuple(problems[:_MAX_DETAIL_ROWS]),
        next_steps=tuple(next_steps),
        data={"layers": layer_rows, "problem_count": len(problems)},
    )


def _check_config_init(context: DoctorContext) -> DiagnosticCheck:
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

        row = _plan_row(plan)
        rows.append(row)
        action_count += len(row["actions"])
        warnings.extend(str(item) for item in plan.warnings)
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
    details = [*blockers, *warnings, *problems]
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
        details=tuple(details[:_MAX_DETAIL_ROWS]),
        next_steps=tuple(dict.fromkeys(next_steps)),
        data={
            "planners": rows,
            "action_count": action_count,
            "warning_count": len(warnings),
            "blocker_count": len(blockers),
        },
    )


def _check_config_sdd(context: DoctorContext) -> DiagnosticCheck:
    """Validate SDD links when an SDD tree exists in this checkout."""
    root = _existing_sdd_root(context.cwd)
    if root is None:
        return DiagnosticCheck(
            id="config.sdd",
            group="config",
            status="SKIP",
            title="SDD validation",
            summary="no SDD tree found in this checkout",
            data={"sdd_root": None},
        )

    validation = validate_sdd_tree(str(root), strict=False)
    issue_rows = [
        {
            "severity": issue.severity,
            "code": issue.code,
            "path": issue.path,
            "message": issue.message,
        }
        for issue in validation.issues
    ]
    error_count = sum(1 for issue in validation.issues if issue.severity == "error")
    warning_count = sum(1 for issue in validation.issues if issue.severity == "warning")
    status: CheckStatus = "WARN" if validation.issues else "OK"
    summary = (
        f"SDD validation passed: {len(validation.files)} files"
        if not validation.issues
        else f"SDD validation found {error_count} errors and {warning_count} warnings"
    )
    details = tuple(
        f"{issue.severity}: {issue.path}: {issue.message} ({issue.code})"
        for issue in validation.issues[:_MAX_DETAIL_ROWS]
    )

    return DiagnosticCheck(
        id="config.sdd",
        group="config",
        status=status,
        title="SDD validation",
        summary=summary,
        details=details,
        next_steps=(f"Run `sase sdd validate -p {root} -W`.",)
        if validation.issues
        else (),
        data={
            "sdd_root": str(validation.root),
            "file_count": len(validation.files),
            "error_count": error_count,
            "warning_count": warning_count,
            "issues": issue_rows[:_MAX_DETAIL_ROWS],
        },
    )


def _plan_row(plan: InitPlan) -> dict[str, Any]:
    return {
        "name": plan.command,
        "label": plan.label,
        "summary": plan.summary,
        "actions": [
            {
                "path": str(action.path),
                "operation": action.operation,
                "detail": action.detail,
            }
            for action in plan.actions[:_MAX_DETAIL_ROWS]
        ],
        "action_count": len(plan.actions),
        "warnings": list(plan.warnings),
        "blockers": list(plan.blockers),
    }


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


def _existing_sdd_root(cwd: Path) -> Path | None:
    for candidate in (cwd / "sdd", cwd / ".sase" / "sdd"):
        if candidate.is_dir():
            return resolve_sdd_root(str(candidate), cwd=cwd)
    return None


__all__ = [
    "config_check_specs",
]
