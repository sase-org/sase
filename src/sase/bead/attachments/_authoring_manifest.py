"""Wire manifest assembly for note attachments."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._authoring_common import finish_wire

if TYPE_CHECKING:
    from collections.abc import Mapping


def build_manifest(
    resolved: dict[int, Path],
    blobs: dict[Path, Any],
    assigned: dict[int, str],
    reuse_refs: list[dict[str, Any]],
    roster: Mapping[str, dict[str, Any]],
    display_bases: Mapping[int, str] | None = None,
    visibilities: Mapping[Path, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build the wire manifest and echo rows for new ingests and reuses."""
    from sase.config import get_machine_name
    from sase.core.rust import require_rust_binding

    sanitize_binding = require_rust_binding("sanitize_attachment_name")
    manifest: list[dict[str, Any]] = []
    echo_rows: list[str] = []
    seen_names: set[str] = set()
    seen_targets: set[Path] = set()
    origin = get_machine_name() or None
    for index in sorted(resolved):
        target = resolved[index]
        name = assigned[index]
        if target not in seen_targets:
            seen_targets.add(target)
            blob = blobs[target]
            base = (display_bases or {}).get(index, target.name)
            sanitized = str(sanitize_binding(base))
            audience = (visibilities or {}).get(target)
            wire, echo_row = finish_wire(
                name=name,
                sanitized=sanitized,
                sha256=blob.sha256,
                size_bytes=blob.size_bytes,
                head=bytes(blob.head),
                object_path=blob.object_path,
                origin=origin,
                visibility=str(audience["visibility"]) if audience else None,
                reason=str(audience["reason"]) if audience else None,
                outcome=str(audience["outcome"]) if audience else None,
            )
            manifest.append(wire)
            seen_names.add(name)
            echo_rows.append(echo_row)
    for ref in reuse_refs:
        name = str(ref.get("name") or "")
        if name in seen_names or name not in roster:
            continue
        seen_names.add(name)
        manifest.append(dict(roster[name]))
    return manifest, echo_rows
