"""Shared artifact-reference normalization, resolution, and serialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from sase.artifact_refs import (
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefResolution,
    artifact_ref_resolution_hint,
    launch_artifact_ref_context,
    parse_artifact_ref,
    resolve_artifact_ref,
)
from sase.core.artifact_file_query_facade import query_artifact_files
from sase.core.artifact_file_types import (
    ArtifactFile,
    artifact_file_to_dict,
)
from sase.core.artifact_file_vcs import materialize_artifact_file


_BARE_FILE_ID_RE = re.compile(r"^(?:default|explicit):[0-9a-f]{24}$")


@dataclass(frozen=True, slots=True)
class ResolvedArtifactReference:
    """One parsed reference, its single resolution, and optional file row."""

    input: str
    canonical_reference: str
    parsed: ArtifactRef
    resolution: ArtifactRefResolution
    file: ArtifactFile | None
    context: ArtifactRefContext | None = None

    @property
    def is_filesystem_backed(self) -> bool:
        return self.parsed.kind_type in {"chat", "document", "file", "bead", "agent"}

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "reference": self.canonical_reference,
            "kind": self.parsed.kind,
            "fragment": (
                None if self.parsed.fragment is None else asdict(self.parsed.fragment)
            ),
            "file": (None if self.file is None else artifact_file_json_dict(self.file)),
            "resolution": _resolution_json_dict(self.resolution),
        }


def _normalize_artifact_reference(value: str) -> str:
    """Expand the supported bare artifact-file id sugar."""

    stripped = value.strip()
    if _BARE_FILE_ID_RE.fullmatch(stripped):
        return f"file:{stripped}"
    return stripped


def resolve_cli_reference(
    value: str,
    *,
    context: ArtifactRefContext | None = None,
) -> ResolvedArtifactReference:
    """Parse, canonically render, resolve once, and attach file metadata."""

    normalized = _normalize_artifact_reference(value)
    parsed = parse_artifact_ref(normalized)
    resolved_context = context or launch_artifact_ref_context(is_home_mode=False)
    resolution = resolve_artifact_ref(parsed, context=resolved_context)
    canonical = resolution.rendered
    file_record = (
        _find_file_record(parsed, context=resolved_context)
        if parsed.kind_type == "file"
        else None
    )
    return ResolvedArtifactReference(
        input=value,
        canonical_reference=canonical,
        parsed=parsed,
        resolution=resolution,
        file=file_record,
        context=resolved_context,
    )


def artifact_file_json_dict(artifact_file: ArtifactFile) -> dict[str, Any]:
    """Serialize every artifact-file field plus its durable reference."""

    payload = artifact_file_to_dict(artifact_file)
    payload["ref"] = f"file:{artifact_file.id}"
    return payload


def _resolution_json_dict(
    resolution: ArtifactRefResolution,
) -> dict[str, object]:
    """Serialize stable resolution details, including every candidate path."""

    return {
        "status": resolution.status,
        "rendered": resolution.rendered,
        "locator": resolution.locator,
        "resolved_path": (
            None if resolution.resolved_path is None else str(resolution.resolved_path)
        ),
        "candidates": list(resolution.candidates),
    }


def resolution_error_lines(result: ResolvedArtifactReference) -> list[str]:
    """Return concise diagnostics for an unresolved CLI reference."""

    lines = [
        f"Error: artifact reference {result.canonical_reference!r} resolved "
        f"with status {result.resolution.status!r}"
    ]
    if result.resolution.locator:
        lines.append(f"locator: {result.resolution.locator}")
    if result.resolution.candidates:
        lines.append("candidates:")
        lines.extend(f"  {candidate}" for candidate in result.resolution.candidates)
    hint = artifact_ref_resolution_hint(
        result.parsed,
        result.resolution,
        context=result.context,
    )
    if hint is not None:
        lines.append(hint)
    return lines


def resolved_file_path(result: ResolvedArtifactReference) -> Path | None:
    """Return a live path, materializing a VCS-backed file row on demand."""

    if (
        result.resolution.status in {"exact", "drifted"}
        and result.resolution.resolved_path is not None
    ):
        return result.resolution.resolved_path
    if (
        result.resolution.status == "vcs_backed"
        and result.file is not None
        and result.context is not None
    ):
        return materialize_artifact_file(
            result.file,
            repositories=result.context.repositories,
        )
    return None


def _find_file_record(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
) -> ArtifactFile | None:
    source = reference.payload.source
    digest = reference.payload.digest
    if source is None or digest is None:
        return None
    artifact_id = f"{source}:{digest}"
    return next(
        (
            artifact_file
            for artifact_file in query_artifact_files(
                context.artifact_index_path,
                limit=None,
            )
            if artifact_file.id == artifact_id
        ),
        None,
    )


__all__ = [
    "ResolvedArtifactReference",
    "artifact_file_json_dict",
    "resolution_error_lines",
    "resolved_file_path",
    "resolve_cli_reference",
]
