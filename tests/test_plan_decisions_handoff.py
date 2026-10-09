"""Handoff-phase coverage for Plan Decisions (sase-1hi.4).

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests._plan_decisions_handoff_helpers import STAMPED_EPIC, STAMPED_TALE
from tests.test_plan_decisions_handoff_bead import (
    test_bead_read_decisions_wire_and_lines,
    test_bead_read_epic_audience_differs_from_phase,
    test_bead_read_epic_lens_and_task_empty,
    test_bead_read_json_envelope_carries_decisions,
    test_bead_read_json_envelope_uses_roots_and_empty_roots_absent,
    test_bead_read_plan_ref_resolves_through_roots,
)
from tests.test_plan_decisions_handoff_coder import (
    AUTO_TALE,
    MEMORY_TALE,
    PENDING_TALE,
    tale_path,
    test_auto_coder_block_says_no_human_reviewed,
    test_builders_pending_and_accepted,
    test_declined_memory_routes_by_audience,
    test_pending_plan_yields_no_coder_block,
    test_reviewer_block_helper_fails_open,
    test_reviewer_block_helper_prefers_archived_copy,
    test_reviewer_coder_block_names_branch_and_default,
)
from tests.test_plan_decisions_handoff_epic import (
    test_epic_context_fails_closed,
    test_epic_context_phase_bead_parent_design_and_successor,
    test_epic_context_resolves_plan_ref_and_skips_missing,
    test_epic_context_resolves_snapshot_and_inherits,
)
from tests.test_plan_decisions_handoff_frozen import (
    FROZEN_MEMORY_TALE,
    test_accepted_frozen_definitions_ignore_reader_env,
    test_accepted_synthetic_fallback_uses_authored_default,
    test_frozen_resolved_path_survives_tmp_load,
)
from tests.test_plan_decisions_handoff_receipt import (
    test_auto_receipt_hook_wires_values_and_label,
    test_receipt_only_posts_with_decisions,
)

__test__ = False

__all__ = [
    "AUTO_TALE",
    "FROZEN_MEMORY_TALE",
    "MEMORY_TALE",
    "PENDING_TALE",
    "STAMPED_EPIC",
    "STAMPED_TALE",
    "tale_path",
    "test_accepted_frozen_definitions_ignore_reader_env",
    "test_accepted_synthetic_fallback_uses_authored_default",
    "test_auto_coder_block_says_no_human_reviewed",
    "test_auto_receipt_hook_wires_values_and_label",
    "test_bead_read_decisions_wire_and_lines",
    "test_bead_read_epic_audience_differs_from_phase",
    "test_bead_read_epic_lens_and_task_empty",
    "test_bead_read_json_envelope_carries_decisions",
    "test_bead_read_json_envelope_uses_roots_and_empty_roots_absent",
    "test_bead_read_plan_ref_resolves_through_roots",
    "test_builders_pending_and_accepted",
    "test_declined_memory_routes_by_audience",
    "test_epic_context_fails_closed",
    "test_epic_context_phase_bead_parent_design_and_successor",
    "test_epic_context_resolves_plan_ref_and_skips_missing",
    "test_epic_context_resolves_snapshot_and_inherits",
    "test_frozen_resolved_path_survives_tmp_load",
    "test_pending_plan_yields_no_coder_block",
    "test_receipt_only_posts_with_decisions",
    "test_reviewer_block_helper_fails_open",
    "test_reviewer_block_helper_prefers_archived_copy",
    "test_reviewer_coder_block_names_branch_and_default",
]
