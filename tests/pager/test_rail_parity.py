"""Parity tests for pager link labels and the ACE link rail."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Literal

import pytest

from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.ace.tui.relations.link_index import _build_link_index
from sase.ace.tui.relations.link_keys import short_ref_label
from sase.ace.tui.widgets.link_rail import _render_link_rail
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager._labels import (
    _DANGLING_ACCENT,
    _DANGLING_ICON,
    _target_marker,
    build_label_layer,
    render_section_with_labels,
)
from sase.pager.document import (
    AttachedTarget,
    PagerDocument,
    PagerOrigin,
    PagerSection,
    target_resolution_ref,
)
from sase.pager.link_scan import LinkSpanKind


_ANCHOR_REF = "bead:anchor"
_PROJECT = "demo"


def _snapshot(rows: tuple[Mapping[str, Any], ...]) -> ArtifactLinksSnapshot:
    return ArtifactLinksSnapshot(rows=rows, source_key=("parity", len(rows)))


def _row(*, source_ref: str, target_ref: str) -> Mapping[str, Any]:
    return {
        "source_ref": source_ref,
        "relation": "related",
        "target_ref": target_ref,
        "description": "parity row",
        "origin": "manual",
        "uses": 1,
        "_project": _PROJECT,
    }


def _document_for_ref(ref: str) -> PagerDocument:
    return PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/parity.txt",
                title="parity.txt",
                kind="file",
                body=f"{ref}\n",
                targets=(
                    AttachedTarget(
                        kind=LinkSpanKind.ARTIFACT_REF.value,
                        target=ref,
                        start=0,
                        end=len(ref),
                    ),
                ),
            ),
        ),
        title="parity",
        origin=PagerOrigin.FILE,
    )


@pytest.mark.parametrize("position", ["source", "target"])
@pytest.mark.parametrize(
    ("ref", "expected_target"),
    [
        (
            "stitch:sase@0123456789abcdef0123456789abcdef01234567",
            ArtifactEntryTarget(
                "stitches", ("sase", "0123456789abcdef0123456789abcdef01234567")
            ),
        ),
        ("patch:42", ArtifactEntryTarget("patches", (_PROJECT, "42"))),
        (
            "bead:sase-uk.9",
            ArtifactEntryTarget("beads", (_PROJECT, "task", "sase-uk.9")),
        ),
        (
            "file:src/sase/pager/app.py",
            ArtifactEntryTarget("files", ("src/sase/pager/app.py",)),
        ),
        ("agent:builder", ArtifactEntryTarget("agents", ("builder",))),
        (
            "plan:202608/link_traversing_pager.md",
            ArtifactEntryTarget(
                "ref:plan",
                (_PROJECT, "archive", "202608/link_traversing_pager.md"),
            ),
        ),
    ],
)
def test_pager_and_link_rail_share_ref_presentation(
    ref: str,
    expected_target: ArtifactEntryTarget,
    position: Literal["source", "target"],
) -> None:
    row = (
        _row(source_ref=ref, target_ref=_ANCHOR_REF)
        if position == "source"
        else _row(source_ref=_ANCHOR_REF, target_ref=ref)
    )
    index = _build_link_index(_snapshot((row,)))
    rail_chip = index.chips_for(_ANCHOR_REF)[0]

    document = _document_for_ref(ref)
    layer = build_label_layer(document, width=120)
    pager_label = layer.labels[0]
    pager_marker = _target_marker(pager_label)

    assert target_resolution_ref(pager_label.target, document.origin) == ref
    assert index.target_for(ref) == expected_target
    assert rail_chip.neighbor_ref == ref
    assert rail_chip.neighbor_target == expected_target
    assert pager_marker.icon == rail_chip.icon
    assert pager_marker.accent == rail_chip.accent
    pager_ref = target_resolution_ref(pager_label.target, document.origin)
    assert pager_ref is not None
    assert short_ref_label(pager_ref) == short_ref_label(rail_chip.neighbor_ref)


def test_pager_and_link_rail_share_dangling_vocabulary() -> None:
    ref = "plan:202608/missing.md"
    index = _build_link_index(
        _snapshot((_row(source_ref=_ANCHOR_REF, target_ref=ref),))
    )
    rail_chip = replace(index.chips_for(_ANCHOR_REF)[0], neighbor_target=None)
    rail = _render_link_rail((rail_chip,), width=120)

    document = _document_for_ref(ref)
    layer = build_label_layer(document, width=120, dangling_refs={ref})
    pager_label = layer.labels[0]
    pager_marker = _target_marker(pager_label)
    pager_text = render_section_with_labels(
        document.sections[0],
        layer.labels_by_section[0],
    )

    assert rail is not None
    assert _DANGLING_ICON in rail.plain
    assert "(missing)" in rail.plain
    assert pager_marker.icon == _DANGLING_ICON
    assert pager_marker.accent == _DANGLING_ACCENT
    assert _DANGLING_ICON in pager_text.plain
    assert "(missing)" in pager_text.plain
