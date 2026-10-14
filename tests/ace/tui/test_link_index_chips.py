"""Chip construction, labels, coercion, and ordering for the link-graph index."""

from __future__ import annotations

import pytest

from sase.ace.tui.relations.link_index import _build_link_index
from tests.ace.tui._link_index_helpers import snapshot

__all__ = [
    "test_awaits_rows_index_with_perspective_labels_and_no_write",
    "test_directed_relation_has_perspective_corrected_labels",
    "test_duplicate_rows_across_projects_converge_to_max_uses",
    "test_empty_snapshot_yields_empty_index",
    "test_ordering_puts_semantic_relations_before_observational",
    "test_projected_row_is_not_writable",
    "test_symmetric_related_labels_both_directions_the_same",
    "test_tolerant_count_coercion_matches_legacy_aggregate_reader",
    "test_tolerant_string_fields_match_legacy_aggregate_reader",
]


def test_empty_snapshot_yields_empty_index() -> None:
    index = _build_link_index(snapshot(()))
    assert index.chips_for("bead:sase-1") == ()
    assert index.target_for("bead:sase-1") is None
    assert "bead:sase-1" not in index.by_ref
    assert "bead:sase-1" not in index.targets_by_ref


def test_directed_relation_has_perspective_corrected_labels() -> None:
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "plan:202608/a.md",
                    "relation": "implements",
                    "target_ref": "bead:sase-1",
                    "description": "lands the design",
                    "origin": "manual",
                    "uses": 1,
                },
            )
        )
    )
    source_chips = index.chips_for("plan:202608/a.md")
    target_chips = index.chips_for("bead:sase-1")
    assert len(source_chips) == 1
    assert len(target_chips) == 1
    assert source_chips[0].label == "implements"
    assert source_chips[0].this_is_source is True
    assert source_chips[0].neighbor_ref == "bead:sase-1"
    assert source_chips[0].why == "lands the design"
    assert target_chips[0].label == "implemented-by"
    assert target_chips[0].this_is_source is False
    assert target_chips[0].neighbor_ref == "plan:202608/a.md"
    assert target_chips[0].directed is True


def test_awaits_rows_index_with_perspective_labels_and_no_write() -> None:
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "agent:alice.athena.9w",
                    "relation": "awaits",
                    "target_ref": "bead:sase-1",
                    "description": "wait_for_beads names bead sase-1",
                    "origin": "projected",
                    "created_by": "projection:agent-wait-bead",
                    "uses": 1,
                },
            )
        )
    )
    source_chips = index.chips_for("agent:alice.athena.9w")
    target_chips = index.chips_for("bead:sase-1")
    assert len(source_chips) == 1
    assert len(target_chips) == 1
    assert source_chips[0].label == "awaits"
    assert source_chips[0].this_is_source is True
    assert source_chips[0].writable is False
    assert target_chips[0].label == "awaited-by"
    assert target_chips[0].this_is_source is False
    assert target_chips[0].writable is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, 1),
        (2.9, 2),
        ("1_000", 1000),
        ("١_٢", 12),
        (-2.9, 0),
        ("-3", 0),
        ("1__000", 0),
        ([], 0),
        ({"a": 1}, 0),
        (None, 0),
    ],
)
def test_tolerant_count_coercion_matches_legacy_aggregate_reader(
    value: object, expected: int
) -> None:
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "bead:source",
                    "relation": "related",
                    "target_ref": "bead:target",
                    "uses": value,
                },
            )
        )
    )
    assert index.chips_for("bead:source")[0].uses == expected


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("description", False, ""),
        ("description", True, "True"),
        ("description", {"a": 1}, "{'a': 1}"),
        ("description", [True, None], "[True, None]"),
        ("origin", 0, ""),
    ],
)
def test_tolerant_string_fields_match_legacy_aggregate_reader(
    field: str, value: object, expected: str
) -> None:
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "bead:source",
                    "relation": "related",
                    "target_ref": "bead:target",
                    field: value,
                },
            )
        )
    )
    chip = index.chips_for("bead:source")[0]
    assert (chip.why if field == "description" else chip.origin) == expected


def test_symmetric_related_labels_both_directions_the_same() -> None:
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "bead:sase-1",
                    "relation": "related",
                    "target_ref": "bead:sase-2",
                    "uses": 1,
                },
            )
        )
    )
    assert index.chips_for("bead:sase-1")[0].label == "related"
    assert index.chips_for("bead:sase-2")[0].label == "related"
    assert index.chips_for("bead:sase-1")[0].directed is False


def test_duplicate_rows_across_projects_converge_to_max_uses() -> None:
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "agent:worker",
                    "relation": "cites",
                    "target_ref": "plan:202608/x.md",
                    "uses": 2,
                    "_project": "alpha",
                },
                {
                    "source_ref": "agent:worker",
                    "relation": "cites",
                    "target_ref": "plan:202608/x.md",
                    "uses": 5,
                    "_project": "beta",
                },
            )
        )
    )
    chips = index.chips_for("agent:worker")
    assert len(chips) == 1
    assert chips[0].uses == 5


def test_ordering_puts_semantic_relations_before_observational() -> None:
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "bead:anchor",
                    "relation": "cites",
                    "target_ref": "plan:202608/z.md",
                    "uses": 1,
                },
                {
                    "source_ref": "bead:anchor",
                    "relation": "implements",
                    "target_ref": "plan:202608/a.md",
                    "uses": 1,
                },
            )
        )
    )
    chips = index.chips_for("bead:anchor")
    assert [chip.relation for chip in chips] == ["implements", "cites"]


def test_projected_row_is_not_writable() -> None:
    index = _build_link_index(
        snapshot(
            (
                {
                    "source_ref": "chop:refresh_docs/refresh_docs",
                    "relation": "launched",
                    "target_ref": "agent:worker",
                    "origin": "projected",
                    "uses": 1,
                },
                {
                    "source_ref": "bead:anchor",
                    "relation": "related",
                    "target_ref": "bead:sase-1",
                    "origin": "manual",
                    "uses": 1,
                },
            )
        )
    )
    assert index.chips_for("agent:worker")[0].writable is False
    assert index.chips_for("bead:anchor")[0].writable is True
