"""Rich and JSON rendering helpers for ``sase plan validate``."""

from __future__ import annotations

import json

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
import yaml  # type: ignore[import-untyped]

from sase.sdd.plan_validate import (
    PlanDiagnostic,
    PlanDiagnosticSeverity,
    PlanFrontmatterFieldSpec,
    PlanValidationResult,
)


def validation_json_payload(
    validation: PlanValidationResult,
    *,
    tier: str,
    path: str,
    schema: tuple[PlanFrontmatterFieldSpec, ...],
) -> dict[str, object]:
    """Build the stable machine-readable validation envelope."""
    return {
        "schema_version": validation.schema_version,
        "ok": validation.ok,
        "tier": tier,
        "path": path,
        "diagnostics": [
            {
                "severity": diagnostic.severity.value,
                "code": diagnostic.code,
                "field_path": diagnostic.field_path,
                "message": diagnostic.message,
                "line": diagnostic.line,
            }
            for diagnostic in validation.diagnostics
        ],
        "expected_schema": {
            "fields": [_field_spec_payload(field) for field in schema],
            "example": _minimal_plan_example(schema),
        },
    }


def render_validation_human(
    validation: PlanValidationResult,
    *,
    tier: str,
    path: str,
    schema: tuple[PlanFrontmatterFieldSpec, ...],
    console: Console,
) -> None:
    """Render location-bearing diagnostics, schema guidance, and a summary."""
    for diagnostic in validation.diagnostics:
        console.print(_diagnostic_text(path, diagnostic), soft_wrap=True)

    if not validation.ok:
        if validation.diagnostics:
            console.print()
        console.print(_schema_table(schema, tier=tier))
        console.print(f"[bold]Minimal valid {tier} plan[/bold]")
        console.print(
            Syntax(
                _minimal_plan_example(schema),
                "yaml",
                word_wrap=True,
                background_color="default",
            )
        )

    error_count = sum(diagnostic.is_error for diagnostic in validation.diagnostics)
    warning_count = sum(
        diagnostic.severity is PlanDiagnosticSeverity.WARNING
        for diagnostic in validation.diagnostics
    )
    if validation.ok:
        summary = Text("Validation passed", style="green")
        summary.append(
            f": {path} is a valid {tier} plan "
            f"({warning_count} {_plural(warning_count, 'warning')})."
        )
        console.print(summary)
    else:
        console.print(
            f"[red]Validation failed[/red]: {error_count} "
            f"{_plural(error_count, 'error')}, {warning_count} "
            f"{_plural(warning_count, 'warning')}."
        )


def _minimal_plan_example(
    schema: tuple[PlanFrontmatterFieldSpec, ...],
) -> str:
    """Build a minimal valid document from the required schema examples."""
    frontmatter = {
        field.name: field.example
        for field in schema
        if field.required and "[]" not in field.name
    }
    yaml_body = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    return f"---\n{yaml_body}\n---\n# Plan\n\nDescribe the implementation.\n"


def _field_spec_payload(field: PlanFrontmatterFieldSpec) -> dict[str, object]:
    return {
        "name": field.name,
        "type": field.field_type,
        "required": field.required,
        "description": field.description,
        "example": field.example,
    }


def _diagnostic_text(path: str, diagnostic: PlanDiagnostic) -> Text:
    location = f"{path}:{diagnostic.line}" if diagnostic.line else path
    severity_style = (
        "bold red"
        if diagnostic.severity is PlanDiagnosticSeverity.ERROR
        else "bold yellow"
    )
    text = Text(f"{location}: ")
    text.append(diagnostic.severity.value, style=severity_style)
    text.append(f" [{diagnostic.code}] ", style="bold")
    text.append(diagnostic.message)
    return text


def _schema_table(schema: tuple[PlanFrontmatterFieldSpec, ...], *, tier: str) -> Table:
    table = Table(
        title=f"Expected {tier} frontmatter schema",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Required", justify="center")
    table.add_column("Description")
    table.add_column("Example")
    for field in schema:
        table.add_row(
            field.name,
            field.field_type,
            "yes" if field.required else "no",
            field.description,
            _example_text(field.example),
        )
    return table


def _example_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else f"{noun}s"


__all__ = [
    "render_validation_human",
    "validation_json_payload",
]
