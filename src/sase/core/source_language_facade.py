"""Typed Python facade for the Rust source-language contract.

Language identity, filename provenance, shebang inspection, and bounded
diff recognition live in ``sase-core``. This module rehydrates wire
payloads through :func:`sase.core.rust.require_rust_binding` with no
Python fallback. A missing or stale wheel raises the project's normal
dependency error rather than a fake unknown language.

Pager producers must not call this facade until activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

SOURCE_LANGUAGE_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _SourceLanguageResult:
    language: str | None
    reason: str
    supported_text: bool


def resolve_source_language(
    *,
    category: str,
    logical_filename: str | None = None,
    prefix: str | None = None,
) -> _SourceLanguageResult:
    """Resolve a canonical language identity through the Rust binding."""
    binding = require_rust_binding("resolve_source_language")
    raw = binding(
        {
            "schema_version": SOURCE_LANGUAGE_WIRE_SCHEMA_VERSION,
            "category": category,
            "logical_filename": logical_filename,
            "prefix": prefix,
        }
    )
    if not isinstance(raw, dict):
        raise TypeError("resolve_source_language returned a non-dict payload")
    schema_version = int(raw.get("schema_version", -1))
    if schema_version != SOURCE_LANGUAGE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported source-language wire schema version "
            f"{schema_version}; expected {SOURCE_LANGUAGE_WIRE_SCHEMA_VERSION}"
        )
    return _SourceLanguageResult(
        language=_optional_str(raw.get("language")),
        reason=str(raw.get("reason") or ""),
        supported_text=bool(raw.get("supported_text")),
    )


def logical_source_filename(
    *,
    source_path: str | None = None,
    vcs_relpath: str | None = None,
    resolved_path: str | None = None,
) -> str | None:
    """Return the logical filename hint from adapter provenance fields."""
    binding = require_rust_binding("logical_source_filename")
    raw = binding(
        {
            "schema_version": SOURCE_LANGUAGE_WIRE_SCHEMA_VERSION,
            "source_path": source_path,
            "vcs_relpath": vcs_relpath,
            "resolved_path": resolved_path,
        }
    )
    return None if raw is None else str(raw)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = [
    "SOURCE_LANGUAGE_WIRE_SCHEMA_VERSION",
    "logical_source_filename",
    "resolve_source_language",
]
