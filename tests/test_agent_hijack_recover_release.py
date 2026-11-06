"""Compatibility facade for hijack release recovery tests.

The concrete tests live in focused modules. Keep their original import path available
without collecting the re-exported test classes a second time.
"""

from __future__ import annotations

from sase.agent.hijack.ledger import HijackLedgerConflict
from sase.agent.hijack.recover_common import RecoveryResult
from sase.agent.hijack.recover_release import (
    RELEASE_ACTIONS,
    recover_release_action,
    restart_availability_reason,
    restart_replacement_conflicts,
)
from tests._agent_hijack_recover_helpers import record as make_record
from tests._agent_hijack_recover_helpers import subject as make_subject
from tests._agent_hijack_recover_release_support import (
    ReleaseLedger,
    ReleasePreview,
    ReleaseRow,
    held_artifacts,
    install_release_ledger,
    recover_args,
    record_for,
    release_deps,
    release_preview,
    release_preview_for_cli,
    release_subject,
)
from tests.test_agent_hijack_recover_release_cli import TestReleaseCli
from tests.test_agent_hijack_recover_release_kill_restart import (
    TestKillRestartHijackRouting,
)
from tests.test_agent_hijack_recover_release_persist import TestPersistRecoverRelease

__all__ = (
    "HijackLedgerConflict",
    "RELEASE_ACTIONS",
    "RecoveryResult",
    "ReleaseLedger",
    "ReleasePreview",
    "ReleaseRow",
    "TestKillRestartHijackRouting",
    "TestPersistRecoverRelease",
    "TestReleaseCli",
    "held_artifacts",
    "install_release_ledger",
    "make_record",
    "make_subject",
    "record_for",
    "recover_args",
    "recover_release_action",
    "release_deps",
    "release_preview",
    "release_preview_for_cli",
    "release_subject",
    "restart_availability_reason",
    "restart_replacement_conflicts",
)

__test__ = False
