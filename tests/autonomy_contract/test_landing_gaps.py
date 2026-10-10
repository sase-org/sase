"""Compatibility facade for the autonomy landing-gap contract tests."""

from __future__ import annotations

# The tests are collected from their split modules; this module only preserves imports.
__test__ = False

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.autonomy.record import (
    apply_record_meta_patch,
    autonomy_inherit_record,
    mutate_record,
    read_record,
    resolve_selection,
    with_legacy_projection,
)
from sase.feature_flags import override_flags
from tests.autonomy_contract import harness

from .test_landing_gaps_inheritance import (
    test_direct_approval_and_recovery_inherit_from_target_project,
    test_host_composed_bare_widening_refused,
    test_host_composed_explicit_manual_narrows,
    test_host_composed_unreadable_predecessor_fails_closed,
    test_human_session_attach_uses_its_prompt_and_standalone_stays_standalone,
    test_in_process_explicit_narrowing_via_real_helper,
    test_in_process_widening_refused_via_real_helper,
    test_successor_prompt_extraction_covers_manual,
)
from .test_landing_gaps_records import (
    test_apply_removes_stale_flag_off,
    test_human_mutation_source_truthful,
    test_record_authoritative_over_stale_legacy,
    test_refresh_preserves_live_record,
)
from .test_landing_gaps_gates import (
    test_contract_suite_publishes_nothing,
    test_empty_adapter_capabilities_ask,
    test_idempotent_creation_reuses_snapshot,
    test_log_agent_shorthand_resolves,
    test_log_since_normalization,
    test_single_evaluation_per_creation,
)

__all__ = [
    "Any",
    "Path",
    "patch",
    "pytest",
    "apply_record_meta_patch",
    "autonomy_inherit_record",
    "mutate_record",
    "read_record",
    "resolve_selection",
    "with_legacy_projection",
    "override_flags",
    "harness",
    "test_apply_removes_stale_flag_off",
    "test_contract_suite_publishes_nothing",
    "test_direct_approval_and_recovery_inherit_from_target_project",
    "test_empty_adapter_capabilities_ask",
    "test_host_composed_bare_widening_refused",
    "test_host_composed_explicit_manual_narrows",
    "test_host_composed_unreadable_predecessor_fails_closed",
    "test_human_mutation_source_truthful",
    "test_human_session_attach_uses_its_prompt_and_standalone_stays_standalone",
    "test_idempotent_creation_reuses_snapshot",
    "test_in_process_explicit_narrowing_via_real_helper",
    "test_in_process_widening_refused_via_real_helper",
    "test_log_agent_shorthand_resolves",
    "test_log_since_normalization",
    "test_record_authoritative_over_stale_legacy",
    "test_refresh_preserves_live_record",
    "test_single_evaluation_per_creation",
    "test_successor_prompt_extraction_covers_manual",
]
