"""Readout classification and aggregation tests.

This module is a facade preserving the original import path. The tests
now live in :mod:`tests.instructions.test_readout_cli`,
:mod:`tests.instructions.test_readout_classify`,
:mod:`tests.instructions.test_readout_build`,
:mod:`tests.instructions.test_readout_staged`, and
:mod:`tests.instructions.test_readout_adapter`; shared fixtures live
in :mod:`tests.instructions._readout_support`. Only public names are
re-exported here, never ``_``-private helpers.
"""

from __future__ import annotations

# The re-exported tests must not be collected twice: pytest collects
# this module (zero tests) and each home module (the real tests).
__test__ = False

from tests.instructions._readout_support import RUN_END, RUN_START
from tests.instructions.test_readout_adapter import (
    test_adapter_binding_rejects_unknown_handoff,
    test_adapter_binding_scores_evidence_matrix,
)
from tests.instructions.test_readout_build import (
    test_build_readout_excludes_monitor_and_gate,
    test_build_readout_groups_modes_and_research,
    test_build_readout_memory_join,
    test_build_readout_missing_done_is_unknown,
    test_build_readout_window_bounds,
    test_delivery_mode_split,
)
from tests.instructions.test_readout_classify import (
    test_classify_aborted_handoff_is_miss,
    test_classify_handoff_beats_accepted_submission,
    test_classify_host_handoff_beats_accepted,
    test_classify_host_monitor_plain_without_tool_calls,
    test_classify_host_monitor_prepared_from_intents,
    test_classify_host_other_handoff,
    test_classify_host_plan_handoff,
    test_classify_miss,
    test_classify_monitor_prepared_needs_real_prepare,
    test_classify_not_required,
    test_classify_other_handoff,
    test_classify_plan_handoff,
)
from tests.instructions.test_readout_cli import (
    test_readout_help_documents_flags,
    test_readout_parser_options_are_alphabetical_with_short_aliases,
    test_readout_rejects_bad_since,
)
from tests.instructions.test_readout_staged import (
    test_aborted_with_accepted_submission_is_accepted,
    test_help_invocations_are_not_handoffs,
    test_legacy_killed_handoff_preserved_with_required_declaration,
    test_plan_validate_alone_is_not_handoff,
    test_staged_handoff_beats_accepted_submission,
    test_staged_not_required_keeps_handoff_class,
    test_staged_plan_clean_missing_declaration_keeps_class,
    test_staged_plan_with_dirty_missing_declaration_is_miss,
    test_staged_prepared_monitor_needs_validated_intent,
)

__all__ = [
    "RUN_END",
    "RUN_START",
    "test_aborted_with_accepted_submission_is_accepted",
    "test_adapter_binding_rejects_unknown_handoff",
    "test_adapter_binding_scores_evidence_matrix",
    "test_build_readout_excludes_monitor_and_gate",
    "test_build_readout_groups_modes_and_research",
    "test_build_readout_memory_join",
    "test_build_readout_missing_done_is_unknown",
    "test_build_readout_window_bounds",
    "test_classify_aborted_handoff_is_miss",
    "test_classify_handoff_beats_accepted_submission",
    "test_classify_host_handoff_beats_accepted",
    "test_classify_host_monitor_plain_without_tool_calls",
    "test_classify_host_monitor_prepared_from_intents",
    "test_classify_host_other_handoff",
    "test_classify_host_plan_handoff",
    "test_classify_miss",
    "test_classify_monitor_prepared_needs_real_prepare",
    "test_classify_not_required",
    "test_classify_other_handoff",
    "test_classify_plan_handoff",
    "test_delivery_mode_split",
    "test_help_invocations_are_not_handoffs",
    "test_legacy_killed_handoff_preserved_with_required_declaration",
    "test_plan_validate_alone_is_not_handoff",
    "test_readout_help_documents_flags",
    "test_readout_parser_options_are_alphabetical_with_short_aliases",
    "test_readout_rejects_bad_since",
    "test_staged_handoff_beats_accepted_submission",
    "test_staged_not_required_keeps_handoff_class",
    "test_staged_plan_clean_missing_declaration_keeps_class",
    "test_staged_plan_with_dirty_missing_declaration_is_miss",
    "test_staged_prepared_monitor_needs_validated_intent",
]
