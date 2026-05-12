"""SQLite summary index for dismissed agent bundle archives."""

from __future__ import annotations

from ._api import (
    archive_bundle_path,
    archive_index_connection,
    archive_index_exists,
    delete_bundle_summaries_for_paths,
    delete_bundle_summaries_for_suffixes,
    next_archive_revision,
    query_bundle_paths_by_suffixes,
    query_summaries,
    rebuild_index,
    upsert_bundle_summary,
    verify_index,
)
from ._bundle_io import archive_maintenance_lock, archive_payload_hash, read_bundle
from ._models import (
    DEFAULT_ARCHIVE_REVISION,
    ERROR_MESSAGE_EXCERPT_CHARS,
    INDEX_FILENAME,
    LEGACY_BUNDLE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    DismissedBundleIndexRebuildResult,
    DismissedBundleIndexVerifyResult,
    DismissedBundleSummary,
)

_DismissedBundleIndexRebuildResult = DismissedBundleIndexRebuildResult
_DismissedBundleIndexVerifyResult = DismissedBundleIndexVerifyResult
_DismissedBundleSummary = DismissedBundleSummary
_read_bundle = read_bundle

__all__ = [
    "DEFAULT_ARCHIVE_REVISION",
    "ERROR_MESSAGE_EXCERPT_CHARS",
    "INDEX_FILENAME",
    "LEGACY_BUNDLE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "DismissedBundleIndexRebuildResult",
    "DismissedBundleIndexVerifyResult",
    "DismissedBundleSummary",
    "_DismissedBundleIndexRebuildResult",
    "_DismissedBundleIndexVerifyResult",
    "_DismissedBundleSummary",
    "_read_bundle",
    "archive_maintenance_lock",
    "read_bundle",
    "archive_bundle_path",
    "archive_index_connection",
    "archive_index_exists",
    "archive_payload_hash",
    "delete_bundle_summaries_for_paths",
    "delete_bundle_summaries_for_suffixes",
    "next_archive_revision",
    "query_bundle_paths_by_suffixes",
    "query_summaries",
    "rebuild_index",
    "upsert_bundle_summary",
    "verify_index",
]
