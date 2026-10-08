"""Handler for ``sase plan validate``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, NoReturn, cast

from sase.main.plan_explain import (
    INVALID_PLAN_TIER_HINT,
    plan_explanation,
)
from sase.main.plan_validate_render import (
    render_validation_human,
    validation_json_payload,
)
from sase.output import console, error_console
from sase.sdd.plan_validate import (
    PlanValidationResult,
    plan_frontmatter_schema,
    validate_plan_file,
)
from sase.sdd.plan_tiers import read_plan_tier


def handle_plan_validate_command(args: argparse.Namespace) -> NoReturn:
    """Validate one explicit plan path and exit with 0/1 status."""
    path_arg = str(args.plan_file)
    path = Path(path_arg)
    authored_tier = read_plan_tier(path)
    tier = authored_tier or "tale"
    schema = plan_frontmatter_schema(tier)
    validation = validate_plan_file(path, tier)
    from sase.sdd.plan_decisions import (
        content_has_decisions_key,
        filter_schema_for_flag,
        is_enabled,
    )

    schema = filter_schema_for_flag(schema)
    try:
        raw_content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raw_content = ""
    if not is_enabled() and content_has_decisions_key(raw_content):
        from sase.sdd.plan_validate import (
            PlanDiagnostic,
            PlanDiagnosticSeverity,
            PlanValidationResult,
        )

        validation = PlanValidationResult(
            schema_version=validation.schema_version,
            ok=False,
            diagnostics=(
                *validation.diagnostics,
                PlanDiagnostic(
                    severity=PlanDiagnosticSeverity.ERROR,
                    code="decisions-disabled",
                    field_path="decisions",
                    message="plan contains decisions: but the plan_decisions flag is off",
                    line=None,
                ),
            ),
            plan=None,
        )
    else:
        validation = _apply_decision_host_checks(
            raw_content, validation, path_arg, tier
        )
    tier_hint = (
        INVALID_PLAN_TIER_HINT
        if authored_tier is None
        and any(
            diagnostic.field_path == "tier" for diagnostic in validation.diagnostics
        )
        else None
    )
    explanation = (
        plan_explanation(authored_tier)
        if args.explain and authored_tier is not None
        else None
    )

    if args.json:
        payload = validation_json_payload(
            validation,
            tier=tier,
            path=path_arg,
            schema=schema,
            explanation=explanation,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if tier_hint is not None:
            error_console.print(tier_hint, style="yellow", soft_wrap=True)
    elif explanation is not None or not args.quiet or not validation.ok:
        render_validation_human(
            validation,
            tier=tier,
            path=path_arg,
            schema=schema,
            console=console if validation.ok else error_console,
            explanation=explanation,
            show_success_summary=not args.quiet,
            tier_hint=tier_hint,
        )

    _print_decision_summary(validation)
    sys.exit(0 if validation.ok else 1)


def _apply_decision_host_checks(
    content: str, validation: PlanValidationResult, path_arg: str, tier: str
) -> PlanValidationResult:
    """Run Plan Decision host checks for validate, honouring flag and context."""
    from sase.sdd.plan_decisions import (
        artifacts_dir_from_env,
        in_agent_context,
        is_enabled,
        validate_host_checks,
    )

    if not is_enabled():
        return validation
    plan = validation.plan
    if plan is None or not getattr(plan, "decisions", cast("Any", ())):
        return validation
    if not in_agent_context():
        print("quote verification runs at propose")
        return validation
    artifacts_dir = artifacts_dir_from_env()
    try:
        extra = validate_host_checks(
            content,
            validation,
            artifacts_dir,
            strict_quotes=True,
        )
    except Exception:
        return validation
    if not extra:
        return validation
    return PlanValidationResult(
        schema_version=validation.schema_version,
        ok=False,
        diagnostics=(*validation.diagnostics, *extra),
        plan=None,
    )


def _print_decision_summary(validation: object) -> None:
    """Print the Decision Sheet, plus the auto-approved note under %auto."""
    try:
        from sase.main.plan_approve_handler import get_auto_plan_approval_action
        from sase.sdd.plan_decisions import is_enabled
    except Exception:
        return
    if not is_enabled():
        return
    plan = getattr(validation, "plan", None)
    if plan is None or not getattr(plan, "decisions", ()):
        return
    _print_decision_sheet(validation)
    try:
        if get_auto_plan_approval_action() is not None:
            print("auto-approved: every decision takes its default")
    except Exception:
        return


def _print_decision_sheet(validation: object) -> None:
    """Render the Decision Sheet the reviewer will see; never fails."""
    try:
        from sase.output import console
        from sase.sdd._plan_display_decisions import pending_decisions_text
        from sase.sdd.plan_decisions import (
            artifacts_dir_from_env,
            build_definitions,
            resolve_binding,
            sheet_binding,
        )
    except Exception:
        return
    try:
        definitions = build_definitions(validation, artifacts_dir_from_env())
        if not definitions:
            return
        resolved = resolve_binding(definitions, {}, "auto")
        values = resolved.get("values")
        if not isinstance(values, dict):
            return
        sheet = sheet_binding(definitions, dict(values), 0)
        console.print(pending_decisions_text(sheet), soft_wrap=True)
    except Exception:
        return


__all__ = ["handle_plan_validate_command"]
