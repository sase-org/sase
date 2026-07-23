"""Validated Python facade for the Rust snippet catalog composer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding


@dataclass(frozen=True, slots=True)
class _ComposedSnippetCatalog:
    """Normalized result from the shared Rust snippet catalog composer."""

    templates: dict[str, str]
    alias_provenance: dict[str, str]


def compose_snippet_catalog(
    explicit_templates: Mapping[str, str],
) -> _ComposedSnippetCatalog:
    """Compose explicit snippet templates through the shared Rust contract."""
    explicit = dict(explicit_templates)
    binding = require_rust_binding("compose_snippet_catalog")
    payload: Any = binding(explicit)
    if not isinstance(payload, Mapping):
        raise TypeError(
            "compose_snippet_catalog returned a non-mapping top-level payload"
        )

    templates = _require_string_mapping(payload.get("templates"), "templates")
    alias_provenance = _require_string_mapping(
        payload.get("alias_provenance"),
        "alias_provenance",
    )

    for alias, source in alias_provenance.items():
        if alias not in templates:
            raise ValueError(
                "compose_snippet_catalog alias provenance references missing "
                f"final template {alias!r}"
            )
        if source not in explicit:
            raise ValueError(
                "compose_snippet_catalog alias provenance references missing "
                f"explicit source {source!r}"
            )

    return _ComposedSnippetCatalog(
        templates=templates,
        alias_provenance=alias_provenance,
    )


def _require_string_mapping(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"compose_snippet_catalog field {field!r} must be a mapping")

    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(
                f"compose_snippet_catalog field {field!r} contains "
                f"non-string key {key!r}"
            )
        if not isinstance(item, str):
            raise TypeError(
                f"compose_snippet_catalog field {field!r} contains "
                f"non-string value for key {key!r}"
            )
        normalized[key] = item
    return normalized


__all__ = ["compose_snippet_catalog"]
