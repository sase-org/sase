"""Child-side before-provider enforcement for keep-work recovery.

Covers phase ``bootstrap_ack``: the reservation descriptor round-trip,
the strict-boot gate in :func:`enforce_recovery_bootstrap` (attempt
identity, goal, bead, permission scope, baseline fingerprints, repository
identities, effective model), the versioned ack persistence, the
expectation-not-proof gather semantics, and the canonical
``hijack_lineage`` key. Every failure case asserts the provider is never
invoked.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.agent.test_recovery_bootstrap_enforce import (
    TestDescriptorRoundTrip,
    TestEnforceFailures,
    TestEnforceSuccess,
)
from tests.agent.test_recovery_bootstrap_gather import (
    TestCollectObservation,
    TestLineageKeys,
    TestParentSideProof,
    TestStrictBootstrapEntry,
    TestVersionedAck,
)

__test__ = False

__all__ = [
    "TestCollectObservation",
    "TestDescriptorRoundTrip",
    "TestEnforceFailures",
    "TestEnforceSuccess",
    "TestLineageKeys",
    "TestParentSideProof",
    "TestStrictBootstrapEntry",
    "TestVersionedAck",
]
