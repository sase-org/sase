"""Handler for ``sase plan validate``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import NoReturn

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


def handle_plan_validate_command(args: argparse.Namespace) -> NoReturn:
    """Validate one explicit plan path and exit with 0/1 status."""
    path_arg = str(args.plan_file)
    tier = str(args.tier)
    schema = plan_frontmatter_schema(tier)
    validation = validate_plan_file(Path(path_arg), tier)

    if args.json:
        payload = validation_json_payload(
            validation,
            tier=tier,
            path=path_arg,
            schema=schema,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif not args.quiet or not validation.ok:
        render_validation_human(
            validation,
            tier=tier,
            path=path_arg,
            schema=schema,
            console=console if validation.ok else error_console,
        )

    sys.exit(0 if validation.ok else 1)


def read_and_validate_plan_file(path: Path, *, tier: str) -> PlanValidationResult:
    """Compatibility facade for propose-time validation callers."""
    return validate_plan_file(path, tier)


__all__ = ["handle_plan_validate_command", "read_and_validate_plan_file"]
