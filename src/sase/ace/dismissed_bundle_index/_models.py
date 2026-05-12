"""Shared models and constants for the dismissed bundle index."""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 2
INDEX_FILENAME = "index.sqlite"
DEFAULT_ARCHIVE_REVISION = 1
LEGACY_BUNDLE_SCHEMA_VERSION = 0
ERROR_MESSAGE_EXCERPT_CHARS = 500


@dataclass(frozen=True)
class DismissedBundleSummary:
    """One indexed dismissed-bundle row."""

    agent_id: str
    raw_suffix: str
    bundle_path: str
    shard: str
    filename: str
    archive_revision: int
    bundle_schema_version: int
    agent_type: str
    cl_name: str
    agent_name: str | None
    status: str
    start_time: str | None
    stop_time: str | None
    dismissed_at: str | None
    revived_at: str | None
    times_revived: int
    project_file: str | None
    project_name: str | None
    model: str | None
    llm_provider: str | None
    runtime: str | None
    vcs_provider: str | None
    workflow: str | None
    is_workflow_child: bool
    parent_timestamp: str | None
    step_index: int | None
    step_name: str | None
    step_type: str | None
    retry_of_timestamp: str | None
    retried_as_timestamp: str | None
    retry_chain_root_timestamp: str | None
    retry_attempt: int
    meta_changespec: str | None
    cost_usd_micros: int | None
    input_tokens: int | None
    output_tokens: int | None
    error_message_excerpt: str | None


@dataclass(frozen=True)
class DismissedBundleIndexVerifyResult:
    """Verification result for the dismissed bundle summary index."""

    ok: bool
    indexed_rows: int
    valid_bundles: int
    corrupt_bundles: int
    stale_rows: int
    missing_rows: int
    fts_missing_rows: int = 0
    fts_orphan_rows: int = 0
    payload_hash_mismatches: int = 0
    orphan_visibility_rows: int = 0
    orphan_revision_rows: int = 0


@dataclass(frozen=True)
class DismissedBundleIndexRebuildResult:
    """Rebuild result for the dismissed bundle summary index."""

    indexed_rows: int
    skipped_corrupt: int
