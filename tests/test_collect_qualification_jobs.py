"""Tests for the qualification fact reader (tools/collect_qualification_jobs).

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests._collect_qualification_jobs_helpers import (
    INVENTORY,
    ROOT,
    SCRIPT,
    collect_tool_fixture as tool,
    release_tool_fixture as release_tool,
)
from tests.test_collect_qualification_jobs_bundle import (
    test_duplicate_scoped_rows_are_preserved_for_refusal,
    test_rerun_carry_forward_evaluates_green,
    test_scope_is_exact_caller_prefix,
    test_success_single_attempt_evaluates_green,
)
from tests.test_collect_qualification_jobs_evidence import (
    test_advisory_jobs_need_no_evidence,
    test_concatenated_streaming_pages_decode_without_slurp,
    test_expired_and_unreadable_payloads_stay_typed,
    test_live_artifact_supersedes_an_expired_tombstone,
    test_missing_upload_is_typed_missing,
)
from tests.test_collect_qualification_jobs_fetch import (
    test_duplicate_artifact_identities_refuse,
    test_fetch_evidence_fails_closed_on_api_errors,
    test_fetch_evidence_refuses_conflicting_payload_bytes,
    test_malformed_pages_refuse,
    test_noncontiguous_attempts_refuse,
)

__test__ = False

__all__ = [
    "INVENTORY",
    "ROOT",
    "SCRIPT",
    "release_tool",
    "test_advisory_jobs_need_no_evidence",
    "test_concatenated_streaming_pages_decode_without_slurp",
    "test_duplicate_artifact_identities_refuse",
    "test_duplicate_scoped_rows_are_preserved_for_refusal",
    "test_expired_and_unreadable_payloads_stay_typed",
    "test_fetch_evidence_fails_closed_on_api_errors",
    "test_fetch_evidence_refuses_conflicting_payload_bytes",
    "test_live_artifact_supersedes_an_expired_tombstone",
    "test_malformed_pages_refuse",
    "test_missing_upload_is_typed_missing",
    "test_noncontiguous_attempts_refuse",
    "test_rerun_carry_forward_evaluates_green",
    "test_scope_is_exact_caller_prefix",
    "test_success_single_attempt_evaluates_green",
    "tool",
]
