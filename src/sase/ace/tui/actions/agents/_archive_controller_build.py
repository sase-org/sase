"""Public import path for Archive corpus building."""

from __future__ import annotations

from typing import Any

from ...models.agent_archive_controller import ArchiveRequestSnapshot
from ._archive_controller_build_pipeline import build_archive_result_pipeline
from ._archive_controller_build_query import row_identity


def build_archive_result(
    owner: Any,
    snapshot: ArchiveRequestSnapshot,
) -> dict[str, Any]:
    """Probe, compile or reuse the handle, and query still-requested windows."""
    return build_archive_result_pipeline(owner, snapshot)


__all__ = ["build_archive_result", "row_identity"]
