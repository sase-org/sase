"""Tests for bead ID relocation helper behavior."""

from __future__ import annotations

from sase.bead.relocation import (
    BeadIdRelocation,
    compose_bead_relocations,
    normalize_bead_relocations,
    resolve_created_bead_id,
    rewrite_text_for_bead_relocations,
)


def test_normalize_bead_relocations_prefers_typed_records() -> None:
    records = normalize_bead_relocations(
        {
            "relocations": [["sase-old", "sase-legacy"]],
            "relocation_records": [
                {
                    "old_id": "sase-1",
                    "new_id": "sase-2",
                    "kind": "top_level_duplicate",
                }
            ],
        }
    )

    assert records == (
        BeadIdRelocation(
            old_id="sase-1",
            new_id="sase-2",
            kind="top_level_duplicate",
        ),
    )


def test_compose_bead_relocations_resolves_children_and_text() -> None:
    composed = compose_bead_relocations(
        (BeadIdRelocation("sase-1", "sase-2", "top_level_duplicate"),),
        (BeadIdRelocation("sase-2", "sase-3", "top_level_duplicate"),),
    )

    assert BeadIdRelocation("sase-1", "sase-3", "top_level_duplicate") in composed
    assert BeadIdRelocation("sase-2", "sase-3", "top_level_duplicate") in composed
    assert resolve_created_bead_id("sase-1", composed) == "sase-3"
    assert resolve_created_bead_id("sase-1.4", composed) == "sase-3.4"
    assert rewrite_text_for_bead_relocations("work sase-1.4", composed) == (
        "work sase-3.4"
    )
