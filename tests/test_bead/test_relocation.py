"""Tests for bead ID relocation helper behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.bead.relocation import (
    BeadIdRelocation,
    _BeadRelocationIdentityError,
    _rewrite_text_for_bead_relocations,
    compose_bead_relocations,
    normalize_bead_relocations,
    relocations_for_subtree,
    resolve_created_bead_id,
    resolve_own_bead_id,
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
    assert _rewrite_text_for_bead_relocations("work sase-1.4", composed) == (
        "work sase-3.4"
    )


def _before_bead(bead_id: str = "sase-1") -> SimpleNamespace:
    return SimpleNamespace(
        id=bead_id,
        issue_type="plan",
        title="Epic",
        created_at="2026-09-24T11:20:35Z",
        created_by="agent-a",
        status="open",
        assignee="",
    )


def test_relocations_for_subtree_keeps_only_own_records() -> None:
    relocations = (
        BeadIdRelocation("sase-1", "sase-9", "top_level_duplicate"),
        BeadIdRelocation("sase-1.2", "sase-9.2", "child"),
        BeadIdRelocation("sase-2", "sase-10", "top_level_duplicate"),
        BeadIdRelocation("sase-11", "sase-12", "top_level_duplicate"),
    )

    assert relocations_for_subtree("sase-1", relocations) == relocations[:2]


def test_resolve_own_bead_id_returns_moved_id_on_identity_match() -> None:
    before = _before_bead()
    moved = SimpleNamespace(
        id="sase-9",
        issue_type="plan",
        title="Epic",
        created_at="2026-09-24T11:20:35Z",
        created_by="agent-a",
        status="in_progress",
        assignee="sase-9.land",
    )

    def show(bead_id: str) -> SimpleNamespace:
        if bead_id == "sase-9":
            return moved
        raise KeyError(bead_id)

    assert (
        resolve_own_bead_id(
            show,
            before,
            (BeadIdRelocation("sase-1", "sase-9", "top_level_duplicate"),),
        )
        == "sase-9"
    )


def test_resolve_own_bead_id_ignores_foreign_relocation() -> None:
    before = _before_bead()
    staying = SimpleNamespace(
        id="sase-1",
        issue_type="plan",
        title="Epic",
        created_at="2026-09-24T11:20:35Z",
        created_by="agent-a",
        status="in_progress",
        assignee="sase-1.land",
    )
    foreign = SimpleNamespace(
        id="sase-99",
        issue_type="flag",
        title="Retire tool_handoff",
        created_at="2026-09-24T11:20:38Z",
        created_by="agent-b",
        status="open",
        assignee="",
    )

    def show(bead_id: str) -> SimpleNamespace:
        if bead_id == "sase-1":
            return staying
        if bead_id == "sase-99":
            return foreign
        raise KeyError(bead_id)

    assert (
        resolve_own_bead_id(
            show,
            before,
            (BeadIdRelocation("sase-1", "sase-99", "top_level_duplicate"),),
        )
        == "sase-1"
    )


def test_resolve_own_bead_id_raises_when_neither_id_matches() -> None:
    before = _before_bead()

    def show(_bead_id: str) -> SimpleNamespace:
        raise KeyError(_bead_id)

    with pytest.raises(_BeadRelocationIdentityError) as excinfo:
        resolve_own_bead_id(
            show,
            before,
            (BeadIdRelocation("sase-1", "sase-9", "top_level_duplicate"),),
        )
    assert "sase-1" in str(excinfo.value)
    assert "sase-9" in str(excinfo.value)


def test_rewrite_matches_child_suffixes_but_not_prefix_hits() -> None:
    relocations = (BeadIdRelocation("sase-17v", "sase-17w", "top_level_duplicate"),)

    assert (
        _rewrite_text_for_bead_relocations("work sase-17v.3 sase-17v.land", relocations)
        == "work sase-17w.3 sase-17w.land"
    )
    assert (
        _rewrite_text_for_bead_relocations("keep sase-17v1 untouched", relocations)
        == "keep sase-17v1 untouched"
    )


def test_rewrite_does_not_chain_relocations() -> None:
    relocations = (
        BeadIdRelocation("sase-a", "sase-b", "top_level_duplicate"),
        BeadIdRelocation("sase-b", "sase-c", "top_level_duplicate"),
    )

    assert _rewrite_text_for_bead_relocations("work sase-a", relocations) == (
        "work sase-b"
    )
