"""Scheduled bounded convergence for already-published run states."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from sase.agents_sync.agent_state_refresh import run_agent_state_refresh
from sase.agents_sync.agent_state_refresh_memo import (
    AgentStateRefreshVerdictMemo,
    UnresolvedVerdictMemoEntry,
)
from sase.agents_sync.inventory_models import InventoryRun, ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_state_repair import StateRepairReport
from sase.agents_sync.v2_io import content_digest, file_reference, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RunRecord,
    V2RunStatePayload,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests.agents_sync.git_sync_fixtures import git, setup_repo, target
from tests.agents_sync._agent_state_refresh_test_support import (
    FINISHED,
    OWNER,
    PROJECT,
    STARTED,
)
from tests.agents_sync._agent_state_refresh_convergence_tests import (
    test_scheduled_convergence_without_another_commit,
)
from tests.agents_sync._agent_state_refresh_scheduler_tests import (
    test_corrupt_and_unsupported_state_reset_safely,
    test_fair_rotation_and_backoff_across_projects,
    test_frozen_window_retries_with_backoff,
    test_killed_tick_backs_off_and_rotates,
    test_missing_owner_identity_is_check_error,
    test_no_enabled_projects_reports_cleanly,
    test_success_advances_cursor_and_end_of_pass_resets,
)
from tests.agents_sync._agent_state_refresh_verdict_tests import (
    test_completed_verdict_pass_prunes_entries_for_runs_that_left_the_window,
    test_corrupt_verdict_memo_entry_is_ignored,
    test_unchanged_unresolved_verdict_is_logged_once_and_changed_evidence_relogs,
    test_unchanged_verdict_skips_filesystem_and_dismissed_lookups,
)

__all__ = [
    "json",
    "subprocess",
    "time",
    "Path",
    "pytest",
    "run_agent_state_refresh",
    "AgentStateRefreshVerdictMemo",
    "UnresolvedVerdictMemoEntry",
    "InventoryRun",
    "ProjectHoodInventory",
    "ProjectTarget",
    "StateRepairReport",
    "content_digest",
    "file_reference",
    "v2_json_bytes",
    "V2HoodSnapshot",
    "V2OwnerHoodEntry",
    "V2OwnerManifest",
    "V2ProjectIdentity",
    "V2RunRecord",
    "V2RunStatePayload",
    "AgentIdentitySnapshot",
    "AgentOwnerIdentity",
    "git",
    "setup_repo",
    "target",
    "OWNER",
    "PROJECT",
    "STARTED",
    "FINISHED",
    "test_corrupt_and_unsupported_state_reset_safely",
    "test_no_enabled_projects_reports_cleanly",
    "test_missing_owner_identity_is_check_error",
    "test_fair_rotation_and_backoff_across_projects",
    "test_success_advances_cursor_and_end_of_pass_resets",
    "test_killed_tick_backs_off_and_rotates",
    "test_frozen_window_retries_with_backoff",
    "test_unchanged_unresolved_verdict_is_logged_once_and_changed_evidence_relogs",
    "test_completed_verdict_pass_prunes_entries_for_runs_that_left_the_window",
    "test_unchanged_verdict_skips_filesystem_and_dismissed_lookups",
    "test_corrupt_verdict_memo_entry_is_ignored",
    "test_scheduled_convergence_without_another_commit",
]
