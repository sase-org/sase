"""Forced name-reuse cleanup failure tests for epic ``sase bead work``.

Facade preserving the original module's public import path. Test bodies live in
:mod:`test_cli_work_epic_launch_cleanup_abort` and
:mod:`test_cli_work_epic_launch_cleanup_sessions`.
"""

from __future__ import annotations

import pytest

from .test_cli_work_epic_launch_cleanup_abort import (
    test_work_agent_session_cleanup_failure_aborts_before_mutation,
    test_work_expected_name_container_conflict_aborts_before_mutation,
    test_work_force_reuse_cleanup_failure_aborts_before_mutation,
)
from .test_cli_work_epic_launch_cleanup_sessions import (
    test_revalidate_raises_when_blocker_appears_after_preview,
    test_select_bead_work_launch_returns_blocked_targets_instead_of_raising,
    test_select_bead_work_launch_uses_one_registry_snapshot,
    test_task_work_accepts_beadless_agent_session_member,
    test_work_agent_session_member_with_ancestor_epic_bead_is_accepted,
    test_work_beadless_agent_session_members_do_not_wedge_retry,
    test_work_conflicting_agent_session_bead_still_blocks,
    test_work_direct_registry_name_mismatch_without_beads_blocks,
    test_work_dry_run_renders_blockers_without_mutating,
    test_work_reports_every_agent_session_blocker_in_one_run,
)

pytestmark = pytest.mark.usefixtures("fake_cli_work_macros")

__all__ = [
    "test_revalidate_raises_when_blocker_appears_after_preview",
    "test_select_bead_work_launch_returns_blocked_targets_instead_of_raising",
    "test_select_bead_work_launch_uses_one_registry_snapshot",
    "test_task_work_accepts_beadless_agent_session_member",
    "test_work_agent_session_cleanup_failure_aborts_before_mutation",
    "test_work_agent_session_member_with_ancestor_epic_bead_is_accepted",
    "test_work_beadless_agent_session_members_do_not_wedge_retry",
    "test_work_conflicting_agent_session_bead_still_blocks",
    "test_work_direct_registry_name_mismatch_without_beads_blocks",
    "test_work_dry_run_renders_blockers_without_mutating",
    "test_work_expected_name_container_conflict_aborts_before_mutation",
    "test_work_force_reuse_cleanup_failure_aborts_before_mutation",
    "test_work_reports_every_agent_session_blocker_in_one_run",
]
