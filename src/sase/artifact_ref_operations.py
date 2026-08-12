"""Rust-backed operations for kind-tagged artifact references."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from sase.artifact_ref_models import (
    ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION,
    ARTIFACT_REF_WIRE_SCHEMA_VERSION,
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefPathFilterResult,
    ArtifactRefPromptCandidate,
    ArtifactRefResolution,
    ArtifactRefResolutionStatus,
    check_record_schema as _check_record_schema,
    optional_str as _optional_str,
)
from sase.core.rust import require_rust_binding


_RESOLUTION_STATUSES = {
    "exact",
    "drifted",
    "vcs_backed",
    "ambiguous",
    "missing",
    "unknown_kind",
    "unknown_repo",
    "unknown_project",
    "filtered",
    "denied",
}


def at_reference_context(
    text: str,
    cursor_offset: int,
    known_kinds: Iterable[str] = (),
) -> dict[str, Any] | None:
    """Return the shared ``@`` context at a Python character offset.

    The Rust binding accepts an LSP UTF-16 position and returns UTF-8 byte
    spans. TUI callers work in Python character offsets, so this facade owns
    both conversions and leaves the widget mapping layer encoding-agnostic.
    """
    position = _lsp_position_for_offset(text, cursor_offset)
    if position is None:
        return None
    binding = require_rust_binding("at_reference_context")
    raw = binding(text, position[0], position[1], list(known_kinds))
    if raw is None:
        return None
    context = dict(cast(Mapping[str, Any], raw))
    for field in ("candidate_span", "replacement_span", "query_span"):
        converted = _utf8_span_to_character_offsets(text, context.get(field))
        if converted is None:
            return None
        context[field] = list(converted)
    return context


def at_reference_menu(
    context: Mapping[str, Any],
    inventory: Mapping[str, Any],
    *,
    payload_index: object | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one shared, I/O-free ``@`` menu from caller-owned inventory."""
    binding = require_rust_binding("at_reference_menu")
    return dict(
        cast(
            Mapping[str, Any],
            binding(
                dict(context),
                dict(inventory),
                payload_index=payload_index,
                options=None if options is None else dict(options),
            ),
        )
    )


def at_reference_inventory(
    payloads: Iterable[Mapping[str, Any]],
) -> object:
    """Build one immutable native payload index outside the keystroke path."""
    binding = require_rust_binding("AtReferenceInventory")
    return binding(payloads=[dict(payload) for payload in payloads])


def _lsp_position_for_offset(text: str, offset: int) -> tuple[int, int] | None:
    """Convert a Python character offset to an LSP UTF-16 position."""
    if offset < 0 or offset > len(text):
        return None
    line_start = text.rfind("\n", 0, offset) + 1
    line = text.count("\n", 0, line_start)
    character = sum(2 if ord(char) > 0xFFFF else 1 for char in text[line_start:offset])
    return line, character


def _utf8_span_to_character_offsets(
    text: str,
    value: object,
) -> tuple[int, int] | None:
    """Convert one Rust UTF-8 byte span into Python character offsets."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(isinstance(offset, int) for offset in value)
    ):
        return None
    start, end = cast(tuple[int, int], tuple(value))
    encoded = text.encode("utf-8")
    if start < 0 or end < start or end > len(encoded):
        return None
    try:
        return (
            len(encoded[:start].decode("utf-8")),
            len(encoded[:end].decode("utf-8")),
        )
    except UnicodeDecodeError:
        return None


def parse_artifact_ref(value: str) -> ArtifactRef:
    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_parse")
    raw = cast(Mapping[str, Any], binding(value))
    return ArtifactRef.from_wire(raw)


def canonicalize_artifact_ref(
    path: str | Path,
    *,
    context: ArtifactRefContext,
) -> str | None:
    _require_artifact_ref_schema()
    normalized = Path(path).expanduser().resolve(strict=False)
    binding = require_rust_binding("artifact_ref_canonicalize")
    result = binding(str(normalized), context.to_wire())
    return None if result is None else str(result)


def resolve_artifact_ref(
    reference: str | ArtifactRef,
    *,
    context: ArtifactRefContext,
) -> ArtifactRefResolution:
    _require_artifact_ref_schema()
    parsed = parse_artifact_ref(reference) if isinstance(reference, str) else reference
    binding = require_rust_binding("artifact_ref_resolve")
    raw = cast(Mapping[str, Any], binding(parsed.to_wire(), context.to_wire()))
    _check_record_schema(raw, record="artifact-reference resolution")
    status = str(raw["status"])
    if status not in _RESOLUTION_STATUSES:
        raise RuntimeError(
            "sase_core_rs returned an unknown artifact-reference resolution "
            f"status: {status}"
        )
    resolved = raw.get("resolved_path")
    return ArtifactRefResolution(
        schema_version=int(raw["schema_version"]),
        status=cast(ArtifactRefResolutionStatus, status),
        rendered=str(raw["rendered"]),
        locator=_optional_str(raw.get("locator")),
        resolved_path=None if resolved is None else Path(str(resolved)),
        candidates=tuple(str(candidate) for candidate in raw["candidates"]),
        diagnostic=_optional_str(raw.get("diagnostic")),
    )


def render_artifact_ref(reference: ArtifactRef) -> str:
    """Render a parsed artifact reference through the shared Rust grammar."""

    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_render")
    return str(binding(reference.to_wire()))


def filter_artifact_ref_paths(
    kind: str,
    candidates: Iterable[str],
    *,
    path_globs: Iterable[str] | None = None,
) -> ArtifactRefPathFilterResult:
    """Filter repo-relative document paths through the shared Rust matcher."""
    _require_artifact_ref_path_filter_schema()
    binding = require_rust_binding("artifact_ref_filter_path_payloads")
    raw = cast(
        Mapping[str, Any],
        binding(
            kind,
            list(candidates),
            None if path_globs is None else list(path_globs),
        ),
    )
    return ArtifactRefPathFilterResult.from_wire(raw)


def scan_artifact_refs(text: str) -> tuple[ArtifactRefPromptCandidate, ...]:
    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_scan_prompt")
    raw = cast(list[Mapping[str, Any]], binding(text))
    return tuple(ArtifactRefPromptCandidate.from_wire(item) for item in raw)


scan_artifact_ref_prompt = scan_artifact_refs


def artifact_ref_kind_catalog() -> tuple[Mapping[str, Any], ...]:
    """Return every compiled-in artifact-reference kind descriptor, raw."""
    binding = require_rust_binding("artifact_ref_kind_catalog")
    raw = cast(list[Mapping[str, Any]], binding())
    for item in raw:
        _check_kind_catalog_record_schema(
            item, record="artifact-reference kind catalog"
        )
    return tuple(raw)


def artifact_ref_parse_canonical(value: str) -> Mapping[str, Any]:
    """Parse one reference after rewriting only its kind label to canonical."""
    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_parse_canonical")
    raw = cast(Mapping[str, Any], binding(value))
    _check_kind_catalog_record_schema(raw, record="canonical artifact-reference parse")
    return raw


def artifact_ref_expansion_validate(expansion_format: str) -> tuple[str, ...]:
    """Validate an expansion format and return the placeholders it uses."""
    binding = require_rust_binding("artifact_ref_expansion_validate")
    return tuple(str(name) for name in binding(expansion_format))


def artifact_ref_expansion_render(
    expansion_format: str,
    values: Mapping[str, str],
) -> str:
    """Render an expansion format, substituting each placeholder verbatim."""
    binding = require_rust_binding("artifact_ref_expansion_render")
    return str(binding(expansion_format, dict(values)))


def artifact_ref_entry_wire_schema_version() -> int:
    """Return the artifact-entry wire schema version."""
    binding = require_rust_binding("artifact_ref_entry_wire_schema_version")
    return int(binding())


def artifact_ref_entry_validate(entry: Mapping[str, Any]) -> None:
    """Validate one normalized artifact entry, raising on a bad shape."""
    binding = require_rust_binding("artifact_ref_entry_validate")
    binding(dict(entry))


def artifact_ref_use_wire_schema_version() -> int:
    """Return the artifact-reference use manifest wire schema version."""
    binding = require_rust_binding("artifact_ref_use_wire_schema_version")
    return int(binding())


def artifact_ref_use_record_render(record: Mapping[str, Any]) -> str:
    """Render one compact JSON artifact-reference use manifest row."""
    binding = require_rust_binding("artifact_ref_use_record_render")
    return str(binding(dict(record)))


def artifact_ref_use_manifest_parse(data: bytes) -> tuple[Mapping[str, Any], ...]:
    """Parse a JSONL artifact-reference use manifest, skipping bad rows."""
    binding = require_rust_binding("artifact_ref_use_manifest_parse")
    raw = cast(list[Mapping[str, Any]], binding(data))
    return tuple(raw)


_ARTIFACT_REF_KIND_CATALOG_WIRE_SCHEMA_VERSION = 1


def _check_kind_catalog_record_schema(
    raw: Mapping[str, Any],
    *,
    record: str,
) -> None:
    version = int(raw["schema_version"])
    if version != _ARTIFACT_REF_KIND_CATALOG_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs returned an unsupported {record} wire: {version}"
        )


def _require_artifact_ref_schema() -> None:
    binding = require_rust_binding("artifact_ref_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_REF_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-reference wire is stale: "
            f"expected {ARTIFACT_REF_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _require_artifact_ref_path_filter_schema() -> None:
    binding = require_rust_binding("artifact_ref_path_filter_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-reference path-filter wire is stale: "
            f"expected {ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION}, got {version}"
        )


__all__ = [
    "at_reference_context",
    "at_reference_inventory",
    "at_reference_menu",
    "artifact_ref_entry_validate",
    "artifact_ref_entry_wire_schema_version",
    "artifact_ref_expansion_render",
    "artifact_ref_expansion_validate",
    "artifact_ref_kind_catalog",
    "artifact_ref_parse_canonical",
    "artifact_ref_use_manifest_parse",
    "artifact_ref_use_record_render",
    "artifact_ref_use_wire_schema_version",
    "canonicalize_artifact_ref",
    "filter_artifact_ref_paths",
    "parse_artifact_ref",
    "render_artifact_ref",
    "resolve_artifact_ref",
    "scan_artifact_ref_prompt",
    "scan_artifact_refs",
]
