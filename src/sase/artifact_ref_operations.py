"""Rust-backed operations for kind-tagged artifact references."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from sase.artifact_ref_models import (
    ARTIFACT_REF_WIRE_SCHEMA_VERSION,
    ArtifactRef,
    ArtifactRefContext,
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
    )


def scan_artifact_refs(text: str) -> tuple[ArtifactRefPromptCandidate, ...]:
    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_scan_prompt")
    raw = cast(list[Mapping[str, Any]], binding(text))
    return tuple(ArtifactRefPromptCandidate.from_wire(item) for item in raw)


scan_artifact_ref_prompt = scan_artifact_refs


def _require_artifact_ref_schema() -> None:
    binding = require_rust_binding("artifact_ref_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_REF_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-reference wire is stale: "
            f"expected {ARTIFACT_REF_WIRE_SCHEMA_VERSION}, got {version}"
        )


__all__ = [
    "at_reference_context",
    "at_reference_inventory",
    "at_reference_menu",
    "canonicalize_artifact_ref",
    "parse_artifact_ref",
    "resolve_artifact_ref",
    "scan_artifact_ref_prompt",
    "scan_artifact_refs",
]
