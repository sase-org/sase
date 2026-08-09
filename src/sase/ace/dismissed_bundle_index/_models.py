"""Shared models and constants for the dismissed bundle index."""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1
INDEX_FILENAME = "index.sqlite"


@dataclass(frozen=True)
class DismissedBundleSummary:
    """One indexed dismissed-bundle row."""

    raw_suffix: str
    bundle_path: str
    shard: str
    filename: str
    agent_type: str
    cl_name: str
    agent_name: str | None
    status: str
    start_time: str | None
    stop_time: str | None
    project_file: str | None
    model: str | None
    llm_provider: str | None
    vcs_provider: str | None
    workflow: str | None
    is_workflow_child: bool
    parent_timestamp: str | None
    step_index: int | None
    step_name: str | None
    retry_of_timestamp: str | None
    retried_as_timestamp: str | None
    retry_chain_root_timestamp: str | None
    retry_attempt: int
    meta_changespec: str | None  # legacy compatibility alias

    @property
    def meta_patch(self) -> str | None:
        """Canonical alias for the legacy summary field."""
        return self.meta_changespec


@dataclass(frozen=True)
class DismissedBundleIndexVerifyResult:
    """Verification result for the dismissed bundle summary index."""

    ok: bool
    indexed_rows: int
    valid_bundles: int
    corrupt_bundles: int
    stale_rows: int
    missing_rows: int


@dataclass(frozen=True)
class DismissedBundleIndexRebuildResult:
    """Rebuild result for the dismissed bundle summary index."""

    indexed_rows: int
    skipped_corrupt: int
