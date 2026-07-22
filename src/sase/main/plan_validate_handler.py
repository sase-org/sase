"""Handler for ``sase plan validate``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import NoReturn

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

    sys.exit(0 if validation.ok else 1)


def read_and_validate_plan_file(path: Path, *, tier: str) -> PlanValidationResult:
    """Compatibility facade for propose-time validation callers."""
    return validate_plan_file(path, tier)


__all__ = ["handle_plan_validate_command", "read_and_validate_plan_file"]
