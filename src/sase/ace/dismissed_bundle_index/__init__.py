"""SQLite summary index for dismissed agent bundle archives."""

from __future__ import annotations

from ._api import (
    archive_index_connection,
    archive_index_exists,
    delete_bundle_summaries_for_suffixes,
    index_signature,
    query_bundle_paths_by_suffixes,
    query_summaries,
    query_summary_identities,
    rebuild_index,
    set_archive_visibility_for_suffixes,
    upsert_bundle_summary,
    verify_index,
)
from ._bundle_io import read_bundle
from ._models import (
    INDEX_FILENAME,
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
    "INDEX_FILENAME",
    "SCHEMA_VERSION",
    "DismissedBundleIndexRebuildResult",
    "DismissedBundleIndexVerifyResult",
    "DismissedBundleSummary",
    "_DismissedBundleIndexRebuildResult",
    "_DismissedBundleIndexVerifyResult",
    "_DismissedBundleSummary",
    "_read_bundle",
    "read_bundle",
    "archive_index_connection",
    "archive_index_exists",
    "delete_bundle_summaries_for_suffixes",
    "index_signature",
    "query_bundle_paths_by_suffixes",
    "query_summaries",
    "query_summary_identities",
    "rebuild_index",
    "set_archive_visibility_for_suffixes",
    "upsert_bundle_summary",
    "verify_index",
]
