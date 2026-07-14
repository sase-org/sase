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
    PLAN_WIRE_SCHEMA_VERSION,
    PlanDiagnostic,
    PlanDiagnosticSeverity,
    PlanValidationResult,
    plan_frontmatter_schema,
    validate_plan,
)


def handle_plan_validate_command(args: argparse.Namespace) -> NoReturn:
    """Validate one explicit plan path and exit with 0/1 status."""
    path_arg = str(args.plan_file)
    tier = str(args.tier)
    schema = plan_frontmatter_schema(tier)
    validation = read_and_validate_plan_file(Path(path_arg), tier=tier)

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
    """Read and validate one plan file without producing output."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        detail = exc.strerror or str(exc)
        return _file_error("file-unreadable", f"cannot read plan file: {detail}")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = raw[: exc.start].count(b"\n") + 1
        return _file_error(
            "utf8-invalid",
            "plan file is not valid UTF-8",
            line=line,
        )
    return validate_plan(content, tier)


def _file_error(
    code: str, message: str, *, line: int | None = None
) -> PlanValidationResult:
    return PlanValidationResult(
        schema_version=PLAN_WIRE_SCHEMA_VERSION,
        ok=False,
        diagnostics=(
            PlanDiagnostic(
                severity=PlanDiagnosticSeverity.ERROR,
                code=code,
                field_path="",
                message=message,
                line=line,
            ),
        ),
        plan=None,
    )


__all__ = ["handle_plan_validate_command", "read_and_validate_plan_file"]
