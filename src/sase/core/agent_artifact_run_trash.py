"""Python facade over the journaled ACE-run trash owner in ``sase_core``.

Shared safety and policy logic lives in the Rust core
(:mod:`sase_core::agent_artifact_run_trash`); this module sequences effects:
it builds the quarantine request from a fresh retention plan, calls the
bindings, and keeps the agent artifact index consistent afterwards.

Index follow-ups never undo the moves: after a quarantine the moved dirs are
deindexed, and after any restore (including restores during a purge) the
restored dirs are re-indexed. Index failures are reported in the result, never
swallowed and never rolled back.

This module is the stable import path. The implementation lives in sibling
modules to keep each file under the 500-line cap, and is re-exported here:

- :mod:`sase.core.agent_artifact_run_trash_models` — wire dataclasses.
- :mod:`sase.core.agent_artifact_run_trash_quarantine` — quarantine.
- :mod:`sase.core.agent_artifact_run_trash_ops` — list, restore, and purge.
- :mod:`sase.core._agent_artifact_run_trash_shared` — binding and path helpers.
"""

from __future__ import annotations

from sase.core.agent_artifact_run_trash_models import (
    AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
    AceRunTrashBatch,
    AceRunTrashItemOutcome,
    AceRunTrashListResult,
    AceRunTrashPurgeResult,
    AceRunTrashQuarantineResult,
    AceRunTrashRestoreResult,
    ReviewedRunSet,
)
from sase.core.agent_artifact_run_trash_ops import (
    list_ace_run_trash,
    purge_ace_run_trash,
    restore_ace_run_trash,
)
from sase.core.agent_artifact_run_trash_quarantine import quarantine_ace_runs


__all__ = [
    "AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION",
    "AceRunTrashBatch",
    "AceRunTrashItemOutcome",
    "AceRunTrashListResult",
    "AceRunTrashPurgeResult",
    "AceRunTrashQuarantineResult",
    "AceRunTrashRestoreResult",
    "ReviewedRunSet",
    "list_ace_run_trash",
    "purge_ace_run_trash",
    "quarantine_ace_runs",
    "restore_ace_run_trash",
]
