"""Worker-safe persistence for TUI edits to macro-backed agent properties.

This module is a facade over the ``_directive_persistence_*`` split: models,
wait-token builders, prompt rewrites, the orchestrated update, and the
autonomy toggle each live in their own module. Only the original public
names are re-exported here so existing import paths keep working.
"""

from __future__ import annotations

from ._directive_persistence_autonomy import persist_autonomy_toggle
from ._directive_persistence_models import (
    AgentDirectivePersistenceSpec,
    AgentMetaPatch,
    AgentTribeStorePatch,
    DirectivePersistenceResult,
    ReadyMarkerPatch,
)
from ._directive_persistence_update import persist_agent_directive_update
from ._directive_persistence_wait import (
    wait_meta_patch_for_token,
    waiting_marker_patch_for_token,
)


__all__ = [
    "AgentDirectivePersistenceSpec",
    "AgentMetaPatch",
    "AgentTribeStorePatch",
    "DirectivePersistenceResult",
    "ReadyMarkerPatch",
    "persist_agent_directive_update",
    "persist_autonomy_toggle",
    "wait_meta_patch_for_token",
    "waiting_marker_patch_for_token",
]
