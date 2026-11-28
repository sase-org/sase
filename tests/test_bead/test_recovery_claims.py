"""Host adapter coverage for recovery activation and claim publication.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_bead._recovery_claims_helpers import (
    FakeRecoveryCore,
    claim_key,
    claim_request,
    recovery_fake_core as fake_core,
)
from tests.test_bead.test_recovery_claims_checkouts import (
    test_competing_publisher_checkouts_keep_one_winner,
    test_interrupted_publication_adopts_the_published_winner,
)
from tests.test_bead.test_recovery_claims_publication import (
    test_concurrent_local_publishers_keep_one_permit,
    test_machine_adapter_uses_writable_store,
    test_malformed_activation_disables_publication,
    test_missing_close_token_never_grants_a_permit,
    test_publication_module_does_not_submit_procs_or_agents,
    test_repeated_reads_preserve_cutoff_and_winner,
    test_two_projects_with_the_same_bead_suffix_stay_isolated,
    test_unconfirmed_push_does_not_grant_a_permit,
)

__test__ = False

__all__ = [
    "FakeRecoveryCore",
    "claim_key",
    "claim_request",
    "fake_core",
    "test_competing_publisher_checkouts_keep_one_winner",
    "test_concurrent_local_publishers_keep_one_permit",
    "test_interrupted_publication_adopts_the_published_winner",
    "test_machine_adapter_uses_writable_store",
    "test_malformed_activation_disables_publication",
    "test_missing_close_token_never_grants_a_permit",
    "test_publication_module_does_not_submit_procs_or_agents",
    "test_repeated_reads_preserve_cutoff_and_winner",
    "test_two_projects_with_the_same_bead_suffix_stay_isolated",
    "test_unconfirmed_push_does_not_grant_a_permit",
]
