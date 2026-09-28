"""Tests for the ace_tool_runs beta flag helper (epic sase-1bt)."""

from __future__ import annotations

from sase.ace.tui.tool_runs.flag import tool_runs_enabled
from sase.feature_flags import FeatureFlag, override_flags
from sase.feature_flags.registry import FEATURE_FLAG_DEFINITIONS


def test_flag_is_registered_as_beta() -> None:
    assert FeatureFlag.ace_tool_runs.value == "ace_tool_runs"
    definition = FEATURE_FLAG_DEFINITIONS[FeatureFlag.ace_tool_runs]
    assert definition.kind == "beta"
    assert definition.default is False
    assert definition.bead == "sase-1bv"


def test_flag_helper_follows_both_flag_states() -> None:
    with override_flags(ace_tool_runs=True):
        assert tool_runs_enabled() is True
    with override_flags(ace_tool_runs=False):
        assert tool_runs_enabled() is False
