"""Compatibility facade for exactly-once hijack recovery tests.

The concrete tests live in focused modules. Keep their original import path available
without collecting the re-exported test classes a second time.
"""

from __future__ import annotations

from sase.agent.hijack.ledger import HijackLedgerConflict
from sase.agent.hijack.recover import recover_hijacked_agent
from sase.agent.hijack.recover_common import (
    InheritanceEvidence,
    RecoveryDeps,
    RecoveryRefusal,
    RecoverySubject,
)
from sase.agent.hijack.recover_settle import (
    gather_recovery_inheritance,
    settle_recovery,
)
from tests._agent_hijack_recover_helpers import FakeLedger, FakePreview, FakeRow
from tests.test_agent_hijack_recover_inheritance import TestGatherInheritance
from tests.test_agent_hijack_recover_launch import TestLaunchedRecovery
from tests.test_agent_hijack_recover_launch_failures import TestQueuedAndFailedLaunches
from tests.test_agent_hijack_recover_refusals import TestRecoveryRefusals
from tests.test_agent_hijack_recover_settle import TestSettleRecovery

__all__ = (
    "FakeLedger",
    "FakePreview",
    "FakeRow",
    "HijackLedgerConflict",
    "InheritanceEvidence",
    "RecoveryDeps",
    "RecoveryRefusal",
    "RecoverySubject",
    "TestGatherInheritance",
    "TestLaunchedRecovery",
    "TestQueuedAndFailedLaunches",
    "TestRecoveryRefusals",
    "TestSettleRecovery",
    "gather_recovery_inheritance",
    "recover_hijacked_agent",
    "settle_recovery",
)

__test__ = False
