"""Configuration and SDD checks for ``sase doctor``."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.config.core import DEPRECATED_TOP_LEVEL_KEYS, load_config_layers
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.main.init_plan import InitPlan
from sase.main.init_registry import iter_init_command_specs
from sase.sdd.links import resolve_sdd_root, validate_sdd_tree

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


@dataclass(frozen=True)
class _ModelPresetScan:
    tokens: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


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
        CheckSpec(
            id="config.model_xprompts",
            group="config",
            title="Model xprompt routing",
            runner=lambda: _check_config_model_xprompts(context),
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
            "deprecated_keys": list(layer.deprecated_keys),
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
        if layer.deprecated_keys:
            location = layer.path or layer.name
            renames = ", ".join(
                f"{key} -> {DEPRECATED_TOP_LEVEL_KEYS[key]}"
                for key in layer.deprecated_keys
            )
            problems.append(f"{location}: deprecated keys (rename): {renames}")

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


def _check_config_model_xprompts(context: DoctorContext) -> DiagnosticCheck:
    """Warn when a model-preset xprompt expands to an unroutable model token.

    Configured ``%model``/``%m`` presets (e.g. ``#m_agy_flash`` expands to
    ``%model:@#agy_flash``) resolve their final model token to a provider at
    launch time. When that token is a bare name that is neither a configured
    ``llm_provider.model_aliases`` entry, an explicit ``provider/model`` target,
    nor a model a registered provider plugin knows, the launch silently falls
    back to the default provider instead of the intended one.

    This read-only guard surfaces that drift — for example a removed
    ``agy_flash`` alias quietly rerouting every ``#agy_*``/``#m_agy_*`` preset to
    the default provider. It is provider-neutral, so it also catches
    ``#m_fable``, ``#m_qwen``, or plugin-provided presets whose tokens stop
    resolving.
    """
    from sase.llm_provider.config import model_alias_names
    from sase.xprompt.loader import get_all_xprompts

    aliases = model_alias_names()
    xprompts = get_all_xprompts(context.project)

    problems: list[dict[str, str]] = []
    scanned = 0
    for name in sorted(xprompts):
        scan = _model_preset_tokens(xprompts[name].content)
        if scan is None:
            continue
        scanned += 1
        for error in scan.errors:
            problems.append(
                {
                    "xprompt": name,
                    "token": "",
                    "message": f"{name}: {error}",
                }
            )
        for token in scan.tokens:
            if _model_token_routes(token, aliases):
                continue
            problems.append(
                {
                    "xprompt": name,
                    "token": token,
                    "message": (
                        f"{name} -> {token} does not resolve to a provider; "
                        "it will fall back to the default provider"
                    ),
                }
            )

    status: CheckStatus = "WARN" if problems else "OK"
    details = tuple(row["message"] for row in problems[:_MAX_DETAIL_ROWS])
    summary = (
        f"{scanned} model preset xprompt(s) route to a provider"
        if not problems
        else f"{len(problems)} model preset token(s) fall back to the default provider"
    )
    next_steps = (
        (
            "Add the unresolved token(s) to `llm_provider.model_aliases`, or "
            "point the xprompt at an explicit `provider/model` target, then rerun "
            "`sase doctor -C config.model_xprompts`.",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.model_xprompts",
        group="config",
        status=status,
        title="Model xprompt routing",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={"scanned": scanned, "problems": problems},
    )


def _model_preset_tokens(content: str) -> _ModelPresetScan | None:
    """Return the final model token(s) a model-preset xprompt expands to.

    Returns ``None`` when *content* does not expand into any ``%model``/``%m``
    directive (so it is not a model preset) or cannot be parsed as a clean
    single/fan-out model directive. Multi-segment prompts carrying several
    explicit ``%model`` directives are split by the launcher, not here, so they
    are skipped rather than reported.
    """
    from sase.xprompt.directives import (
        DirectiveError,
        extract_prompt_directives,
        has_model_directive,
        split_prompt_for_models,
    )
    from sase.xprompt.processor import process_xprompt_references

    try:
        expanded = process_xprompt_references(content)
    except Exception:  # noqa: BLE001 - a malformed preset must not break doctor.
        return None

    if not has_model_directive(expanded):
        return None

    try:
        branches = split_prompt_for_models(expanded)
        sources = branches if branches else [expanded]
        tokens: list[str] = []
        for source in sources:
            _, directives = extract_prompt_directives(source)
            if directives.model:
                tokens.append(directives.model)
    except DirectiveError as exc:
        return _ModelPresetScan(errors=(str(exc),))
    except Exception:  # noqa: BLE001 - a malformed preset must not break doctor.
        return None
    return _ModelPresetScan(tokens=tuple(tokens))


def _model_token_routes(token: str, aliases: set[str]) -> bool:
    """Return ``True`` when *token* routes to a concrete provider.

    A token is routable when it resolves to a known provider, is a configured
    alias (whose target provider plugin may simply be uninstalled on this
    machine), or uses explicit ``provider/model`` syntax. Only a bare, unknown
    token that is none of these silently falls back to the default provider.
    """
    from sase.llm_provider.registry import resolve_model_provider

    provider, _ = resolve_model_provider(token)
    if provider is not None:
        return True
    if token in aliases:
        return True
    return "/" in token


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
