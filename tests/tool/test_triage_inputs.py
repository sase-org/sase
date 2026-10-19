"""Wire-valid selection evidence and stored triage diagnostics.

Split into focused modules; this module re-exports every public name so the
original import path keeps working. It collects no tests itself. Only public
names are re-exported here, never ``_``-private helpers.
"""

from __future__ import annotations

import importlib

import pytest

from tests.tool.test_triage_inputs_executor import (
    test_execute_triage_stage_continues_for_selection_witness,
    test_execute_triage_stage_waits_for_tool_store_writer,
    test_gatherer_timeout_stores_diagnostic_and_keeps_exit_code,
    test_settle_exception_stores_diagnostic_and_keeps_exit_code,
)
from tests.tool.test_triage_inputs_gather import (
    test_gather_selection_records_emits_wire_valid_items,
    test_gather_selection_records_empty_failures_are_empty_items,
    test_gather_selection_records_extraction_error_drops_items,
    test_gather_selection_records_skips_old_mtime_before_parse,
)
from tests.tool.test_triage_inputs_settle import (
    test_classify_accepts_gathered_selection_records,
    test_selection_record_flows_through_settle_and_stage,
)

pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_triage_settle"),
    reason="triage bindings are not in this wheel",
)

# The re-exported tests must not be collected twice: pytest collects
# this module (zero tests) and each home module (the real tests).
__test__ = False

__all__ = [
    "pytestmark",
    "test_classify_accepts_gathered_selection_records",
    "test_execute_triage_stage_continues_for_selection_witness",
    "test_execute_triage_stage_waits_for_tool_store_writer",
    "test_gather_selection_records_emits_wire_valid_items",
    "test_gather_selection_records_empty_failures_are_empty_items",
    "test_gather_selection_records_extraction_error_drops_items",
    "test_gather_selection_records_skips_old_mtime_before_parse",
    "test_gatherer_timeout_stores_diagnostic_and_keeps_exit_code",
    "test_selection_record_flows_through_settle_and_stage",
    "test_settle_exception_stores_diagnostic_and_keeps_exit_code",
]
