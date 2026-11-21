"""Retention planning for per-project ACE-run artifact directories.

Protection facts (bead liveness, continuation ancestry, artifact-index
references, scan markers) are gathered here from their own Rust-backed
sources; the final preview classification, the canonical-root/symlink-ancestor
safety check, and the bottom-up empty-shard walk all live in the
``sase_core_rs`` run-retention owner (:mod:`sase_core::agent_artifact_run_retention`).
Mutation is retired: ``apply_ace_run_retention`` calls the owner only to
receive its stable refusal and never performs protection scans, filesystem
deletion, or artifact-index deindexing.

This module is the stable import path. The implementation lives in sibling
modules to keep each file under the 500-line cap, and is re-exported here:

- :mod:`sase.core.agent_artifact_run_retention_models` — wire dataclasses.
- :mod:`sase.core.agent_artifact_run_retention_plan` — preview and apply refusal.
- :mod:`sase.core.agent_artifact_run_retention_candidates` — candidate scan.
- :mod:`sase.core._agent_artifact_run_retention_shared` — path and month helpers.
"""

from __future__ import annotations

from sase.core._agent_artifact_run_retention_shared import recent_month_names
from sase.core.agent_artifact_run_protection import (
    collect_ace_run_retention_protections,
)
from sase.core.agent_artifact_run_retention_candidates import (
    plan_continuation_run_retention,
    protection_reasons_for_dirs,
)
from sase.core.agent_artifact_run_retention_models import (
    ACE_RUN_RETENTION_SCHEMA_VERSION,
    DEFAULT_ACE_RUN_KEEP_RECENT_MONTHS,
    AceRunProtectionSnapshot,
    AceRunRetentionApplyResult,
    AceRunRetentionCounts,
    AceRunRetentionItem,
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    EmptyAceRunShard,
    ProtectedAceRunItem,
)
from sase.core.agent_artifact_run_retention_plan import (
    apply_ace_run_retention,
    plan_ace_run_retention,
)


__all__ = [
    "ACE_RUN_RETENTION_SCHEMA_VERSION",
    "DEFAULT_ACE_RUN_KEEP_RECENT_MONTHS",
    "AceRunProtectionSnapshot",
    "AceRunRetentionApplyResult",
    "AceRunRetentionCounts",
    "AceRunRetentionItem",
    "AceRunRetentionPlan",
    "AceRunRetentionPolicy",
    "EmptyAceRunShard",
    "ProtectedAceRunItem",
    "apply_ace_run_retention",
    "collect_ace_run_retention_protections",
    "plan_ace_run_retention",
    "plan_continuation_run_retention",
    "protection_reasons_for_dirs",
    "recent_month_names",
]
