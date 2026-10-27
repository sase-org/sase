"""Failed-close recovery at the terminal finalizer boundary.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_finalizers_failed_close_recovery_close import (
    TestClosePlusBeforeCommitFailure,
    TestClosePlusDeclarationRecoveryFailure,
)
from tests.test_finalizers_failed_close_recovery_controls import TestControls
from tests.test_finalizers_failed_close_recovery_handoff import (
    TestHandoffAndIdentity,
    TestMultipleCloses,
    TestPublicationFailure,
)
from tests.test_finalizers_failed_close_recovery_landing import TestLandingProofs

__test__ = False

__all__ = [
    "TestClosePlusBeforeCommitFailure",
    "TestClosePlusDeclarationRecoveryFailure",
    "TestControls",
    "TestHandoffAndIdentity",
    "TestLandingProofs",
    "TestMultipleCloses",
    "TestPublicationFailure",
]
