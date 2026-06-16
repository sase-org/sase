"""Typed Python adapter over the Rust frontmatter schema & validation API.

This module wraps the ``sase_core_rs`` bindings (``frontmatter_field_schema``,
``frontmatter_input_type_schema``, ``validate_frontmatter``,
``validate_frontmatter_field``) into typed Python objects so later phases (the
prompt frontmatter panel, the input collection modal) never touch binding dict
shapes directly.

All field/value validation rules and guidance text live in ``sase-core`` (the
same engine that backs the xprompt LSP), so the TUI panel and the editor never
drift. Nothing here reimplements a validation rule; this module only rehydrates
the binding output into dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from sase.core.rust import require_rust_binding


class FrontmatterFieldKind(Enum):
    """Structural shape of a frontmatter field (mirrors the Rust enum).

    Drives which editor the panel uses for each property.
    """

    SCALAR = "scalar"
    LIST = "list"
    BOOL_OR_LIST = "bool_or_list"
    BOOL_OR_SCALAR = "bool_or_scalar"
    STRUCTURED = "structured"


class DiagnosticSeverity(Enum):
    """Severity of a frontmatter diagnostic (mirrors the editor wire enum)."""

    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"
    HINT = "hint"


@dataclass(frozen=True)
class FrontmatterFieldSchema:
    """A panel-oriented descriptor for one supported frontmatter field.

    Attributes:
        name: The field key (e.g. ``description``).
        kind: The structural shape used to pick an editor.
        required: Whether the field must be present (always ``False`` today).
        description: One-line summary, shared with hover/LSP guidance.
        allowed_values: Optional human hint describing allowed values.
        example: A short example value for the field.
    """

    name: str
    kind: FrontmatterFieldKind
    required: bool
    description: str
    allowed_values: str | None
    example: str


@dataclass(frozen=True)
class FrontmatterInputType:
    """A panel-oriented descriptor for one supported ``input`` type.

    Attributes:
        name: Canonical type name (e.g. ``int``).
        aliases: Accepted aliases for the canonical name (e.g. ``integer``).
        rule: One-line human rule describing accepted values (modal guidance).
    """

    name: str
    aliases: tuple[str, ...]
    rule: str


@dataclass(frozen=True)
class EditorPosition:
    """A zero-based ``(line, character)`` position in the validated text."""

    line: int
    character: int


@dataclass(frozen=True)
class EditorRange:
    """A half-open ``[start, end)`` span in the validated text."""

    start: EditorPosition
    end: EditorPosition


@dataclass(frozen=True)
class FrontmatterDiagnostic:
    """A single validation diagnostic, matching the xprompt LSP output.

    Attributes:
        range: The span the diagnostic applies to.
        severity: How severe the issue is.
        code: A stable machine code (e.g.
            ``invalid_xprompt_frontmatter_input_type``).
        message: The human-readable diagnostic message.
    """

    range: EditorRange
    severity: DiagnosticSeverity
    code: str
    message: str

    @property
    def is_error(self) -> bool:
        """Return ``True`` when this diagnostic is an error."""
        return self.severity is DiagnosticSeverity.ERROR


def _field_from_dict(payload: dict[str, Any]) -> FrontmatterFieldSchema:
    return FrontmatterFieldSchema(
        name=payload["name"],
        kind=FrontmatterFieldKind(payload["kind"]),
        required=payload["required"],
        description=payload["description"],
        allowed_values=payload.get("allowed_values"),
        example=payload["example"],
    )


def _input_type_from_dict(payload: dict[str, Any]) -> FrontmatterInputType:
    return FrontmatterInputType(
        name=payload["name"],
        aliases=tuple(payload["aliases"]),
        rule=payload["rule"],
    )


def _position_from_dict(payload: dict[str, Any]) -> EditorPosition:
    return EditorPosition(line=payload["line"], character=payload["character"])


def _diagnostic_from_dict(payload: dict[str, Any]) -> FrontmatterDiagnostic:
    span = payload["range"]
    return FrontmatterDiagnostic(
        range=EditorRange(
            start=_position_from_dict(span["start"]),
            end=_position_from_dict(span["end"]),
        ),
        severity=DiagnosticSeverity(payload["severity"]),
        code=payload["code"],
        message=payload["message"],
    )


def frontmatter_field_schema() -> list[FrontmatterFieldSchema]:
    """Return the ordered panel frontmatter field descriptors from core."""
    binding = require_rust_binding("frontmatter_field_schema")
    return [_field_from_dict(item) for item in binding()]


def input_type_schema() -> list[FrontmatterInputType]:
    """Return the supported ``input`` type catalog from core."""
    binding = require_rust_binding("frontmatter_input_type_schema")
    return [_input_type_from_dict(item) for item in binding()]


def validate_frontmatter(text: str) -> list[FrontmatterDiagnostic]:
    """Validate a whole frontmatter block via core.

    Args:
        text: A complete ``---``-delimited frontmatter block (the canonical
            form the panel serializes) or a bare YAML body without delimiters.

    Returns:
        Diagnostics matching the xprompt LSP output (same engine).
    """
    binding = require_rust_binding("validate_frontmatter")
    return [_diagnostic_from_dict(item) for item in binding(text)]


def validate_frontmatter_field(field: str, value: str) -> list[FrontmatterDiagnostic]:
    """Validate a single frontmatter field value via core.

    Args:
        field: The field key (e.g. ``snippet``).
        value: The YAML text that would follow ``field:`` — a single-line
            scalar/list, or a multi-line YAML block for structured values.

    Returns:
        Diagnostics matching the xprompt LSP output for that field.
    """
    binding = require_rust_binding("validate_frontmatter_field")
    return [_diagnostic_from_dict(item) for item in binding(field, value)]
