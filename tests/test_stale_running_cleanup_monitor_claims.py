"""Tests for stale RUNNING cleanup of ace-monitor and ace-gate claims.

The tests live in focused support modules while this original module remains
as their collection and import facade.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.scheduler import stale_running_sweep as cleanup_module
from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries
from sase.running_field import WorkspaceClaim

from tests._stale_running_cleanup_monitor_claims_imports import (
    test_cleanup_skip_monitor_claims_survives_unimportable_monitor_start,
    test_cleanup_imports_monitor_claim_label_when_not_skipping_monitor_claims,
    test_cleanup_never_imports_monitor_start,
)
from tests._stale_running_cleanup_monitor_claims_retention import (
    test_cleanup_releases_dead_gate_claim_after_held_ttl,
    test_cleanup_keeps_dead_gate_claim_when_held_ttl_disabled,
    test_cleanup_repairs_leaked_monitor_claim_with_stray_sheet,
    test_cleanup_keeps_leaked_monitor_claim_with_real_dirt,
    test_cleanup_sweep_never_reaches_workspace_provider_ensure,
)
from tests._stale_running_cleanup_monitor_claims_terminal import (
    test_cleanup_keeps_dead_monitor_claim_when_member_not_terminal,
    test_cleanup_releases_dead_monitor_claim_once_member_is_terminal,
    test_cleanup_keeps_dead_gate_claim_when_member_not_terminal,
    test_cleanup_releases_dead_gate_claim_once_member_is_terminal,
    test_cleanup_skip_monitor_claims_leaves_ace_monitor_claims_untouched,
)
