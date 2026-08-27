"""Repair helpers for stale artifact-read file hints."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...artifact_reads import ArtifactReadRefSpec

_RECOVERABLE_STATUSES = frozenset({"exact", "drifted", "vcs_backed"})


def repair_artifact_read_path(spec: ArtifactReadRefSpec) -> str | None:
    """Return a live path for a recorded artifact read, or ``None``."""
    if not spec.cwd:
        return None
    try:
        from sase.artifact_cli.references import (
            resolve_cli_reference,
            resolved_file_path,
        )
        from sase.artifact_ref_context import artifact_ref_context
        from sase.sdd.files import get_primary_workspace_dir
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution

        workspace, workspace_num = workspace_context_for_plan_resolution(spec.cwd)
        primary = get_primary_workspace_dir(str(workspace), workspace_num)
        anchors = [(workspace, workspace_num)]
        primary_path = Path(primary).expanduser().resolve(strict=False)
        if primary_path != workspace:
            anchors.append((primary_path, 1))

        for anchor, num in anchors:
            context = artifact_ref_context(anchor, num)
            result = resolve_cli_reference(spec.ref, context=context)
            if result.resolution.status not in _RECOVERABLE_STATUSES:
                continue
            path = resolved_file_path(result)
            if path is not None and path.is_file():
                return str(path)
    except (ImportError, OSError, RuntimeError, ValueError):
        return None
    return None
