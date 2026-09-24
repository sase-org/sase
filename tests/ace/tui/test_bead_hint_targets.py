"""Tests for the bead-hint ref helpers."""

from __future__ import annotations

from sase.ace.tui.bead_hint_targets import (
    bead_hint_target,
    bead_id_from_hint_target,
)


def test_valid_id_with_whitespace_maps_to_bead_ref() -> None:
    assert bead_hint_target("  sase-14j.5  ") == "bead:sase-14j.5"


def test_invalid_or_empty_ids_map_to_none() -> None:
    assert bead_hint_target("not a bead id!!") is None
    assert bead_hint_target("") is None
    assert bead_hint_target("   ") is None


def test_round_trip_returns_clean_id() -> None:
    assert (
        bead_id_from_hint_target(bead_hint_target("sase-14j.5") or "") == "sase-14j.5"
    )


def test_paths_and_malformed_bead_strings_map_to_none() -> None:
    assert bead_id_from_hint_target("/tmp/notes.md") is None
    assert bead_id_from_hint_target("~/notes.md") is None
    assert bead_id_from_hint_target("bead:bad id!!") is None
    assert bead_id_from_hint_target("bead:") is None
    assert bead_id_from_hint_target("pages/sase-1/sase-1.md") is None
