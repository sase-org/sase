"""Thin ToolRun ledger adapter over ``sase_core_rs``.

Rust owns catalog normalization, fingerprints, the SQLite store, retention
selection, and queries. This module is a wire-only facade: the
implementations live in sibling ``tool_run_*`` modules (kept under the
500-line cap) and are re-exported here so existing ``sase.core.tool_run``
imports keep working. Typed view rows live in ``sase.core.tool_run_views``.

``require_rust_binding`` stays a settable module attribute: the sibling
modules resolve it here at call time, so patching
``sase.core.tool_run.require_rust_binding`` (or any public name above)
behaves exactly as it did when this file held the implementation.
"""

from sase.core.rust import require_rust_binding
from sase.core.tool_run_definitions import (
    tool_run_canonicalize_fingerprint,
    tool_run_duration_calibration,
    tool_run_duration_fit,
    tool_run_normalize_definition,
    tool_run_sync_wait_budget,
    tool_run_unknown_evidence,
    tool_run_wire_schema_version,
)
from sase.core.tool_run_lifecycle import (
    tool_run_activate_staged_join,
    tool_run_append_event,
    tool_run_begin,
    tool_run_claim,
    tool_run_finish,
    tool_run_join,
    tool_run_observe,
    tool_run_reconcile,
    tool_run_release_join,
    tool_run_release_staged_join,
    tool_run_request_stop,
    tool_run_reserve_staged_join,
)
from sase.core.tool_run_paths import tool_run_store_path, tools_dir
from sase.core.tool_run_queries import (
    tool_run_briefs,
    tool_run_detail,
    tool_run_list,
    tool_run_live_glance,
    tool_run_node_summaries,
    tool_run_receipt_lookup,
    tool_run_receipt_settle,
    tool_run_receipts_report,
    tool_run_record_demand,
    tool_run_retention_apply,
    tool_run_retention_preview,
    tool_run_show,
    tool_run_stats_report,
    tool_run_store_stats,
    tool_run_summary,
)
from sase.core.tool_run_triage import (
    tool_run_failures,
    tool_run_triage_classify,
    tool_run_triage_extract,
    tool_run_triage_record,
    tool_run_triage_settle,
    tool_run_triage_show,
    tool_run_triage_stage,
    tool_run_triage_verdict,
)
from sase.core.tool_run_views import (
    ToolRunBrief,
    ToolRunBriefs,
    ToolRunDetail,
    ToolRunDetailStage,
    ToolRunDetailStageCounts,
    ToolRunDetailTriageItem,
    ToolRunExpectedStage,
    ToolRunGlance,
    ToolRunGlanceStage,
    ToolRunLiveGlance,
    ToolRunLogMetadata,
    ToolRunNodeSummaries,
    ToolRunNodeSummary,
    ToolRunVerdictSummary,
)

__all__ = [
    "ToolRunBrief",
    "ToolRunBriefs",
    "ToolRunDetail",
    "ToolRunDetailStage",
    "ToolRunDetailStageCounts",
    "ToolRunDetailTriageItem",
    "ToolRunExpectedStage",
    "ToolRunGlance",
    "ToolRunGlanceStage",
    "ToolRunLiveGlance",
    "ToolRunLogMetadata",
    "ToolRunNodeSummaries",
    "ToolRunNodeSummary",
    "ToolRunVerdictSummary",
    "tool_run_append_event",
    "tool_run_begin",
    "tool_run_briefs",
    "tool_run_detail",
    "tool_run_canonicalize_fingerprint",
    "tool_run_claim",
    "tool_run_duration_calibration",
    "tool_run_duration_fit",
    "tool_run_finish",
    "tool_run_list",
    "tool_run_live_glance",
    "tool_run_node_summaries",
    "tool_run_normalize_definition",
    "tool_run_observe",
    "tool_run_reconcile",
    "tool_run_receipt_lookup",
    "tool_run_receipt_settle",
    "tool_run_receipts_report",
    "tool_run_record_demand",
    "tool_run_stats_report",
    "tool_run_request_stop",
    "tool_run_retention_apply",
    "tool_run_retention_preview",
    "tool_run_failures",
    "tool_run_join",
    "tool_run_release_join",
    "tool_run_activate_staged_join",
    "tool_run_release_staged_join",
    "tool_run_reserve_staged_join",
    "tool_run_show",
    "tool_run_sync_wait_budget",
    "tool_run_store_path",
    "tool_run_store_stats",
    "tool_run_summary",
    "tool_run_triage_classify",
    "tool_run_triage_extract",
    "tool_run_triage_record",
    "tool_run_triage_settle",
    "tool_run_triage_show",
    "tool_run_triage_stage",
    "tool_run_triage_verdict",
    "tool_run_unknown_evidence",
    "tool_run_wire_schema_version",
    "tools_dir",
]
