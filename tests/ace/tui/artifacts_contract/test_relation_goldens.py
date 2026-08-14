"""Frozen Patch relation oracle: chains, cycles, missing parents, families."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.ace.patch import Patch
from sase.ace.tui.models.patch_graph_index import build_patch_graph_index
from sase.ace.tui.widgets.ancestors_children_panel import AncestorsChildrenPanel

_GOLDEN = Path(__file__).resolve().parent / "goldens" / "relations" / "cases.json"


class _RelationshipProbe(AncestorsChildrenPanel):
    """Widget-free probe so relation goldens do not need a Textual app."""

    def __init__(self) -> None:
        self._ancestors: list[str] = []
        self._ancestor_statuses: dict[str, str] = {}
        self._hidden_ancestor_count = 0
        self._hidden_descendant_count = 0
        self._hidden_reverted_sibling_count = 0
        self._sibling_statuses: dict[str, str] = {}


def _cases() -> dict[str, Any]:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def _patch(item: dict[str, Any]) -> Patch:
    return Patch(
        name=str(item["name"]),
        description="d",
        parent=item.get("parent"),
        status=str(item.get("status") or "Ready"),
        file_path="/tmp/demo.sase",
        line_number=1,
    )


def test_relation_cases_match_current_patch_graph() -> None:
    cases = _cases()
    assert cases["cross_kind_edges"] == []
    probe = _RelationshipProbe()
    for name, case in cases.items():
        if name == "cross_kind_edges":
            continue
        patches = [_patch(item) for item in case["patches"]]
        index = build_patch_graph_index(patches)
        selected = next(item for item in patches if item.name == case["from"])
        ancestors = probe._find_ancestors(selected, index)
        siblings = probe._find_siblings(selected, index)
        children = [child.name for child in index.get_children(selected.name)]
        assert ancestors == case["ancestors"], name
        assert siblings == case["siblings"], name
        assert children == case["children"], name
