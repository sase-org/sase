"""Private staging and durable publication-protection state.

Split from a single module into focused modules; this package preserves the
original ``tests.agents_sync.test_publication_protection`` import path and
re-exports every public test for backward compatibility.
"""

from __future__ import annotations

from tests.agents_sync.test_publication_protection.test_ledger_rescan import (
    test_clean_scan_resolves_transient_unverified_state,
    test_stale_scanner_block_is_rescanned_and_superseded_on_clean,
    test_stale_scanner_block_that_still_hits_is_reblocked_with_current_evidence,
)
from tests.agents_sync.test_publication_protection.test_scan_staging import (
    test_clean_scan_stages_private_bytes_and_copies_only_the_verified_digest,
    test_hit_is_withheld_and_persists_only_metadata_across_restart,
    test_nonclean_scan_never_authorizes_copy,
)
from tests.agents_sync.test_publication_protection.test_scanner_resilience import (
    test_missing_scanner_binding_is_unverified_and_value_free,
    test_oversized_text_is_skipped_without_raising_scanner_limit,
    test_scanner_exception_is_unverified_and_preserves_source,
    test_symlink_candidate_is_withheld,
)

__all__ = [
    "test_clean_scan_resolves_transient_unverified_state",
    "test_clean_scan_stages_private_bytes_and_copies_only_the_verified_digest",
    "test_hit_is_withheld_and_persists_only_metadata_across_restart",
    "test_missing_scanner_binding_is_unverified_and_value_free",
    "test_nonclean_scan_never_authorizes_copy",
    "test_oversized_text_is_skipped_without_raising_scanner_limit",
    "test_scanner_exception_is_unverified_and_preserves_source",
    "test_stale_scanner_block_is_rescanned_and_superseded_on_clean",
    "test_stale_scanner_block_that_still_hits_is_reblocked_with_current_evidence",
    "test_symlink_candidate_is_withheld",
]
