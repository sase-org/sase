"""End-to-end seam tests for forced agent-name-reuse ``,x`` relaunches.

Commit 0835b38d2 ("feat(ace): migrate Patch and agent producers to durable
argv") changed ``LaunchProcMixin._submit_launch_proc()`` to submit argv-only
``python -m sase run`` through the durable proc supervisor and discard the
in-process worker body that used to rewrite ``%id(!name)`` prompts and wipe
the reserved name before relaunch. These tests pin the fix at the seam that
actually runs in production: the ``RUN_LAUNCH`` request payload ACE submits,
and how the ``sase run`` child (``launch_query()``) consumes it.

Facade preserving the original ``tests.test_force_reuse_launch_seam``
import path. The tests now live in the sibling
``test_force_reuse_launch_seam_*`` modules and are re-exported here, so
existing imports keep working.
"""

from __future__ import annotations

from tests.test_force_reuse_launch_seam_consume import (
    test_launch_query_consumes_authorized_agent_session_form,
    test_launch_query_consumes_authorized_payload_and_wipes_reserved_name,
    test_launch_query_fanout_contradiction_surfaces_clear_error,
    test_launch_query_parse_failure_records_and_emits,
    test_launch_query_threads_multi_prompt_segment_envs,
    test_launch_query_wipe_failure_records_and_emits,
    test_prepared_kill_and_edit_prompt_survives_submit_then_launch_query,
)
from tests.test_force_reuse_launch_seam_registry import (
    test_forced_agent_session_member_relaunch_keeps_its_parent_resolvable,
    test_launch_query_real_agent_session_cleanup_failure_prevents_spawn,
    test_launch_query_wipes_real_agent_session_registry_before_spawn,
)
from tests.test_force_reuse_launch_seam_rejection import (
    test_plain_sase_run_without_request_sidecar_still_rejects_forced_reuse,
    test_sidecar_without_authorization_still_rejects_forced_reuse,
)
from tests.test_force_reuse_launch_seam_submission import (
    test_kill_and_edit_submission_authorizes_forced_reuse_agent_session_form,
    test_kill_and_edit_submission_authorizes_forced_reuse_clan_form,
    test_marked_bulk_kill_and_edit_each_pane_authorizes_its_own_forced_name,
)

__test__ = False

__all__ = [
    "test_forced_agent_session_member_relaunch_keeps_its_parent_resolvable",
    "test_kill_and_edit_submission_authorizes_forced_reuse_agent_session_form",
    "test_kill_and_edit_submission_authorizes_forced_reuse_clan_form",
    "test_launch_query_consumes_authorized_agent_session_form",
    "test_launch_query_consumes_authorized_payload_and_wipes_reserved_name",
    "test_launch_query_fanout_contradiction_surfaces_clear_error",
    "test_launch_query_parse_failure_records_and_emits",
    "test_launch_query_real_agent_session_cleanup_failure_prevents_spawn",
    "test_launch_query_threads_multi_prompt_segment_envs",
    "test_launch_query_wipe_failure_records_and_emits",
    "test_launch_query_wipes_real_agent_session_registry_before_spawn",
    "test_marked_bulk_kill_and_edit_each_pane_authorizes_its_own_forced_name",
    "test_plain_sase_run_without_request_sidecar_still_rejects_forced_reuse",
    "test_prepared_kill_and_edit_prompt_survives_submit_then_launch_query",
    "test_sidecar_without_authorization_still_rejects_forced_reuse",
]
