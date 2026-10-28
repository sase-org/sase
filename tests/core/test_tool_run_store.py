"""Compatibility facade for the tool-run store tests."""

from __future__ import annotations

import importlib

import pytest

from tests.core._tool_run_store_busy import test_store_adapters_delegate_busy_policy
from tests.core._tool_run_store_lifecycle import (
    test_adapter_round_trip_and_unknown_evidence,
    test_handoff_reserve_claim_stop_finish_reconcile,
    test_observe_persists_child_facts_and_reconcile_authorizes_reap,
    test_tools_dir_is_under_sase_home,
)
from tests.core._tool_run_store_triage import (
    test_triage_binding_round_trips,
    test_triage_settle_stores_location_matched_owner_only,
)

__all__ = [
    "test_adapter_round_trip_and_unknown_evidence",
    "test_handoff_reserve_claim_stop_finish_reconcile",
    "test_observe_persists_child_facts_and_reconcile_authorizes_reap",
    "test_store_adapters_delegate_busy_policy",
    "test_tools_dir_is_under_sase_home",
    "test_triage_binding_round_trips",
    "test_triage_settle_stores_location_matched_owner_only",
]


pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_begin"),
    reason="tool_run bindings are not in this wheel",
)
