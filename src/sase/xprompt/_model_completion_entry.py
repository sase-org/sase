"""Entry dataclass and wire schema for ``%model`` completions."""

from __future__ import annotations

from dataclasses import dataclass, field

#: Wire schema understood by existing Rust LSP versions. Alias metadata is
#: additive under v1 so old readers ignore it and new readers can still load
#: stale v1 catalogs that omit it.
MODEL_COMPLETION_CATALOG_SCHEMA_VERSION = 1

MODEL_COMPLETION_ENTRY_WIRE_FIELDS: tuple[str, ...] = (
    "value",
    "display",
    "description",
    "kind",
    "provider",
    "aliases",
    "alias_kind",
    "target_provider",
    "target_model",
    "target_effort",
    "provenance",
    "reference",
    "reference_effort",
    "selector_mode",
    "pool_available",
    "pool_total",
    "config_source",
    "bucket",
    "advisory_label",
    "advisory_severity",
    "provider_model_count",
)

MODEL_COMPLETION_INT_FIELDS = frozenset(
    {"pool_available", "pool_total", "provider_model_count"}
)


@dataclass(frozen=True, slots=True)
class ModelCompletionEntry:
    """One inline-completable ``%model`` value."""

    value: str
    display: str
    description: str = ""
    kind: str = "model"
    provider: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    alias_kind: str = ""
    target_provider: str = ""
    target_model: str = ""
    target_effort: str = ""
    provenance: str = ""
    reference: str = ""
    reference_effort: str = ""
    selector_mode: str = ""
    pool_available: int = 0
    pool_total: int = 0
    config_source: str = ""
    bucket: str = ""
    advisory_label: str = ""
    advisory_severity: str = ""
    provider_model_count: int = 0


__all__ = [
    "MODEL_COMPLETION_CATALOG_SCHEMA_VERSION",
    "MODEL_COMPLETION_ENTRY_WIRE_FIELDS",
    "MODEL_COMPLETION_INT_FIELDS",
    "ModelCompletionEntry",
]
