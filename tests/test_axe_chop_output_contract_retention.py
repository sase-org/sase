"""Output-contract tests for the artifact-run-prune, epic-launch-flush, and
notification-store-compact chops.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_axe_chop_output_contract_retention_flush_compact import (
    test_epic_launch_flush_emits_noop_summary,
    test_notification_store_compact_emits_action_summary,
    test_notification_store_compact_emits_missing_store_summary,
    test_notification_store_compact_emits_noop_summary,
)
from tests.test_axe_chop_output_contract_retention_prune import (
    test_artifact_run_prune_busy_trash_lock_skips_notification,
    test_artifact_run_prune_emits_noop_summary,
    test_artifact_run_prune_notifies_when_protection_sources_are_unavailable,
    test_artifact_run_prune_preview_uses_configured_grace_days,
    test_artifact_run_prune_preview_uses_project_unavailable_label,
    test_artifact_run_prune_purges_before_plan_and_snapshot,
    test_artifact_run_prune_supersedes_stale_preview_key,
    test_artifact_run_prune_upserts_actionable_preview_notification,
)
from tests.test_axe_chop_output_contract_retention_prune_real_store import (
    test_artifact_run_prune_real_store_empty_shards_only_preview_notifies,
    test_artifact_run_prune_real_store_protection_warning_deduplicates,
    test_artifact_run_prune_real_store_reclaimable_preview_uses_aware_timestamps,
    test_artifact_run_prune_real_store_repeat_appends_aware_plus_one,
    test_artifact_run_prune_real_store_supersedes_changed_preview,
)

__test__ = False

__all__ = [
    "test_artifact_run_prune_busy_trash_lock_skips_notification",
    "test_artifact_run_prune_emits_noop_summary",
    "test_artifact_run_prune_notifies_when_protection_sources_are_unavailable",
    "test_artifact_run_prune_preview_uses_configured_grace_days",
    "test_artifact_run_prune_preview_uses_project_unavailable_label",
    "test_artifact_run_prune_purges_before_plan_and_snapshot",
    "test_artifact_run_prune_real_store_empty_shards_only_preview_notifies",
    "test_artifact_run_prune_real_store_protection_warning_deduplicates",
    "test_artifact_run_prune_real_store_reclaimable_preview_uses_aware_timestamps",
    "test_artifact_run_prune_real_store_repeat_appends_aware_plus_one",
    "test_artifact_run_prune_real_store_supersedes_changed_preview",
    "test_artifact_run_prune_supersedes_stale_preview_key",
    "test_artifact_run_prune_upserts_actionable_preview_notification",
    "test_epic_launch_flush_emits_noop_summary",
    "test_notification_store_compact_emits_action_summary",
    "test_notification_store_compact_emits_missing_store_summary",
    "test_notification_store_compact_emits_noop_summary",
]
