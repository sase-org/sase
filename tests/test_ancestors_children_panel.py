"""Tests for relation-layout Patch sibling logic."""

from sase.ace.patch import Patch
from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.models.changespec_graph_index import (
    build_patch_graph_index,
)
from sase.ace.tui.relations import build_patches_relation_index
from sase.ace.tui.widgets.artifacts.patch_entry import patch_row_target
from sase.core.artifact_relation_layout import (
    RelationEntryFact,
    build_relation_view,
)
from conftest import _PatchFactory


def _find_siblings_and_keys(
    current_name: str,
    current_status: str,
    sibling_specs: list[tuple[str, str]],
    hide_reverted: bool = False,
) -> tuple[int, list[str], dict[str, str]]:
    """Build the shared relation view and return sibling labels and keys.

    Args:
        current_name: Name of the currently selected Patch.
        current_status: Status of the currently selected Patch.
        sibling_specs: List of (name, status) tuples for other Patches.
        hide_reverted: Whether to hide reverted/archived siblings.

    Returns:
        Tuple of (hidden_count, sibling_names, sibling_keys).
    """
    current = _PatchFactory.create(name=current_name, status=current_status)
    all_cs: list[Patch] = [current] + [
        _PatchFactory.create(name=n, status=s) for n, s in sibling_specs
    ]
    graph_index = build_patch_graph_index(all_cs)
    contract = compile_builtin_contract("patches", label="Patch", icon="", accent="")
    relation_index = build_patches_relation_index(
        all_cs,
        graph_index,
        contract=contract,
    )
    facts = {
        patch_row_target(patch): RelationEntryFact(
            label=patch.name,
            status=patch.status,
            hidden=hide_reverted
            and (
                patch.status.startswith("Reverted")
                or patch.status.startswith("Archived")
            ),
        )
        for patch in all_cs
    }
    view = build_relation_view(
        index=relation_index,
        origin=patch_row_target(current),
        relations=contract.relations,
        facts=facts,
    )
    sibling_section = next(
        section for section in view.sections if section.relation == "siblings"
    )
    siblings = [row.label for row in sibling_section.rows]
    keys = dict(view.keymap.siblings)
    return sibling_section.hidden_count, siblings, keys


def test_non_suffixed_sibling_sorts_first() -> None:
    """Non-suffixed sibling (suffix_num=0) should sort before suffixed ones."""
    _, siblings, _ = _find_siblings_and_keys(
        current_name="pat_no_last_7_days__2",
        current_status="Reverted",
        sibling_specs=[
            ("pat_no_last_7_days__1", "Reverted"),
            ("pat_no_last_7_days", "Ready"),
        ],
    )
    assert siblings == ["pat_no_last_7_days", "pat_no_last_7_days__1"]


def test_hide_reverted_keeps_ready_sibling_from_suffixed() -> None:
    """With hide_reverted=True, a Ready (non-suffixed) sibling should still be shown."""
    _, siblings, _ = _find_siblings_and_keys(
        current_name="foo__1",
        current_status="Reverted",
        sibling_specs=[
            ("foo", "Ready"),
            ("foo__2", "Reverted"),
        ],
        hide_reverted=True,
    )
    assert siblings == ["foo"]
