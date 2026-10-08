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
    try:
        raw_content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raw_content = ""
    is_json = bool(args.json)
    validation = _apply_decision_host_checks(
        raw_content, validation, path_arg, tier, json_mode=is_json
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
        decision_envelope = _decision_json_envelope(validation)
        if decision_envelope is not None:
            payload["decisions"] = decision_envelope
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

    _print_decision_summary(validation, to_stdout=not is_json)
    sys.exit(0 if validation.ok else 1)


def _decision_json_envelope(validation: object) -> dict[str, object] | None:
    """Build the machine-readable Decision Sheet envelope for ``--json``."""
    plan = getattr(validation, "plan", None)
    if plan is None or not getattr(plan, "decisions", ()):
        return None
    try:
        from sase.main.plan_approve_handler import get_auto_plan_approval_action
        from sase.sdd._plan_display_decisions import pending_decisions_text
        from sase.sdd.plan_decisions import (
            artifacts_dir_from_env,
            build_definitions,
            in_agent_context,
            resolve_binding,
            sheet_binding,
        )
    except Exception:
        return None
    try:
        definitions = build_definitions(validation, artifacts_dir_from_env())
        if not definitions:
            return None
        resolved = resolve_binding(definitions, {}, "auto")
        values = resolved.get("values")
        if not isinstance(values, dict):
            return None
        sheet = sheet_binding(definitions, dict(values), 0)
        sheet_text = pending_decisions_text(sheet).plain
        try:
            auto_approved = get_auto_plan_approval_action() is not None
        except Exception:
            auto_approved = False
        envelope: dict[str, object] = {
            "sheet": sheet,
            "sheet_text": sheet_text,
            "auto_approved": auto_approved,
            "auto_note": (
                "auto-approved: every decision takes its default"
                if auto_approved
                else None
            ),
        }
        if not in_agent_context():
            envelope["quote_verification"] = "quote verification runs at propose"
        return envelope
    except Exception:
        return None


def _apply_decision_host_checks(
    content: str,
    validation: PlanValidationResult,
    path_arg: str,
    tier: str,
    *,
    json_mode: bool = False,
) -> PlanValidationResult:
    """Run Plan Decision host checks for validate."""
    from sase.sdd.plan_decisions import (
        artifacts_dir_from_env,
        in_agent_context,
        validate_host_checks,
    )

    plan = validation.plan
    if plan is None or not getattr(plan, "decisions", cast("Any", ())):
        return validation
    if not in_agent_context():
        if json_mode:
            print("quote verification runs at propose", file=sys.stderr)
        else:
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
    except Exception as exc:
        from sase.sdd.plan_validate import PlanDiagnostic, PlanDiagnosticSeverity

        extra = [
            PlanDiagnostic(
                severity=PlanDiagnosticSeverity.ERROR,
                code="decision-host-check-failed",
                field_path="decisions",
                message=f"plan decision host checks failed: {exc}",
                line=None,
            )
        ]
    if not extra:
        return validation
    return PlanValidationResult(
        schema_version=validation.schema_version,
        ok=False,
        diagnostics=(*validation.diagnostics, *extra),
        plan=None,
    )


def _print_decision_summary(validation: object, *, to_stdout: bool = True) -> None:
    """Print the Decision Sheet, plus the auto-approved note under %auto.

    In ``--json`` mode ``to_stdout`` is False so stdout stays one JSON
    document: the sheet and the ``%auto`` note go to stderr while the same
    content also lives inside the JSON envelope.
    """
    try:
        from sase.main.plan_approve_handler import get_auto_plan_approval_action
    except Exception:
        return
    plan = getattr(validation, "plan", None)
    if plan is None or not getattr(plan, "decisions", ()):
        return
    _print_decision_sheet(validation, to_stdout=to_stdout)
    try:
        if get_auto_plan_approval_action() is not None:
            if to_stdout:
                print("auto-approved: every decision takes its default")
            else:
                print(
                    "auto-approved: every decision takes its default",
                    file=sys.stderr,
                )
    except Exception:
        return


def _print_decision_sheet(validation: object, *, to_stdout: bool = True) -> None:
    """Render the Decision Sheet the reviewer will see; never fails."""
    try:
        from sase.output import console, error_console
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
        out = console if to_stdout else error_console
        out.print(pending_decisions_text(sheet), soft_wrap=True)
    except Exception:
        return


__all__ = ["handle_plan_validate_command"]
