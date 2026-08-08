"""Rust-backed codec and presentation helpers for artifact-reference lists."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.artifact_ref_models import (
    ARTIFACT_REF_WIRE_SCHEMA_VERSION,
    ArtifactRefContext,
    ArtifactRefResolution,
    ArtifactRefResolutionStatus,
)
from sase.core.rust import require_rust_binding
from sase.sdd.plan_ref_display import (
    PLAN_REFERENCE_ARROW,
    PLAN_REFERENCE_MISSING_LABEL,
)


ARTIFACT_REF_LIST_RESOLUTION_WIRE_SCHEMA_VERSION = 2

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
}


@dataclass(frozen=True, slots=True)
class ArtifactRefListEntry:
    """One rendered reference and its machine-local resolution outcome."""

    rendered: str
    resolution: ArtifactRefResolution

    def to_wire(self) -> dict[str, object]:
        """Return the plain JSON-compatible shape emitted by the Rust codec."""

        resolution = self.resolution
        resolution_wire: dict[str, object] = {
            "schema_version": resolution.schema_version,
            "status": resolution.status,
            "rendered": resolution.rendered,
            "locator": resolution.locator,
            "resolved_path": (
                None
                if resolution.resolved_path is None
                else str(resolution.resolved_path)
            ),
            "candidates": list(resolution.candidates),
        }
        if resolution.diagnostic is not None:
            resolution_wire["diagnostic"] = resolution.diagnostic
        return {
            "rendered": self.rendered,
            "resolution": resolution_wire,
        }


def normalize_artifact_ref_list(entries: Iterable[str]) -> tuple[str, ...]:
    """Canonicalize, deduplicate, and preserve the order of stored references."""

    _require_list_resolution_schema()
    binding = require_rust_binding("artifact_ref_list_normalize")
    return tuple(str(entry) for entry in binding(list(entries)))


def resolve_artifact_ref_list(
    entries: Iterable[str],
    *,
    context: ArtifactRefContext,
) -> tuple[ArtifactRefListEntry, ...]:
    """Resolve a stored reference list in one batched Rust call."""

    _require_list_resolution_schema()
    binding = require_rust_binding("artifact_ref_list_resolve")
    raw = cast(
        Mapping[str, Any],
        binding(list(entries), context.to_wire()),
    )
    schema_version = int(raw["schema_version"])
    if schema_version != ARTIFACT_REF_LIST_RESOLUTION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an unsupported artifact-reference list "
            f"resolution wire: {schema_version}"
        )
    return tuple(
        _entry_from_wire(cast(Mapping[str, Any], entry))
        for entry in cast(Iterable[Mapping[str, Any]], raw.get("entries", ()))
    )


def artifact_ref_list_display_lines(
    entries: Iterable[ArtifactRefListEntry | str],
) -> tuple[str, ...]:
    """Render each stable reference followed by its resolved path or marker."""

    lines: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            rendered = entry
            resolved_path = None
        else:
            rendered = entry.rendered
            resolved_path = entry.resolution.resolved_path
        lines.append(rendered)
        detail = (
            PLAN_REFERENCE_MISSING_LABEL
            if resolved_path is None
            else str(resolved_path)
        )
        if detail != rendered:
            lines.append(f"{PLAN_REFERENCE_ARROW} {detail}")
    return tuple(lines)


def _entry_from_wire(raw: Mapping[str, Any]) -> ArtifactRefListEntry:
    resolution_raw = cast(Mapping[str, Any], raw["resolution"])
    schema_version = int(resolution_raw["schema_version"])
    if schema_version != ARTIFACT_REF_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an unsupported artifact-reference "
            f"resolution wire: {schema_version}"
        )
    status = str(resolution_raw["status"])
    if status not in _RESOLUTION_STATUSES:
        raise RuntimeError(
            "sase_core_rs returned an unknown artifact-reference resolution "
            f"status: {status}"
        )
    resolved_path = resolution_raw.get("resolved_path")
    resolution = ArtifactRefResolution(
        schema_version=schema_version,
        status=cast(ArtifactRefResolutionStatus, status),
        rendered=str(resolution_raw["rendered"]),
        locator=_optional_str(resolution_raw.get("locator")),
        resolved_path=(None if resolved_path is None else Path(str(resolved_path))),
        candidates=tuple(
            str(candidate) for candidate in resolution_raw.get("candidates", ())
        ),
        diagnostic=_optional_str(resolution_raw.get("diagnostic")),
    )
    return ArtifactRefListEntry(
        rendered=str(raw["rendered"]),
        resolution=resolution,
    )


def _require_list_resolution_schema() -> None:
    binding = require_rust_binding("artifact_ref_list_resolution_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_REF_LIST_RESOLUTION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-reference list resolution wire is stale: "
            f"expected {ARTIFACT_REF_LIST_RESOLUTION_WIRE_SCHEMA_VERSION}, "
            f"got {version}"
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


__all__ = [
    "ARTIFACT_REF_LIST_RESOLUTION_WIRE_SCHEMA_VERSION",
    "ArtifactRefListEntry",
    "artifact_ref_list_display_lines",
    "normalize_artifact_ref_list",
    "resolve_artifact_ref_list",
]
