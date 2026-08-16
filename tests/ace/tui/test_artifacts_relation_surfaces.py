"""Surface tests for Artifacts relation capability wiring."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_actions import CAPABILITY_HOST_ACTIONS
from sase.ace.tui.artifact_tabs import PaneCapability, resolve_artifacts_subtabs
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.help_modal.patches_artifact_bindings import _relation_rows


def test_relations_capability_has_registered_host_actions() -> None:
    assert CAPABILITY_HOST_ACTIONS[PaneCapability.RELATIONS] == (
        "start_ancestor_mode",
        "start_child_mode",
        "start_sibling_mode",
        "beads_open_plan",
        "plans_open_bead",
    )


def test_relation_help_rows_follow_contract_capability() -> None:
    km = load_keymap_registry({})
    for descriptor in resolve_artifacts_subtabs():
        contract = descriptor.resolved_contract
        rows = _relation_rows(km, contract)
        if contract.has(PaneCapability.RELATIONS):
            assert rows
            assert all(len(description) <= 32 for _key, description in rows)
        else:
            assert rows == []
