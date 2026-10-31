"""Filesystem-backed agent metadata enrichment public import path."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agent import Agent

__all__ = ["enrich_agent_from_meta"]


def enrich_agent_from_meta(
    agent: Agent,
    artifacts_dir: str | None,
    *,
    workflow_child: bool = False,
) -> None:
    """Read agent_meta.json and populate model/vcs_provider fields.

    Args:
        agent: The Agent to enrich (modified in place).
        artifacts_dir: Path to the artifacts directory, or None.
    """
    # Imported lazily so the TUI startup closure keeps the split impl/turn/
    # waiting modules off first paint. Callers bind this wrapper at import.
    from ._meta_enrichment_filesystem_impl import (
        enrich_agent_from_meta as _enrich_agent_from_meta,
    )

    _enrich_agent_from_meta(agent, artifacts_dir, workflow_child=workflow_child)
