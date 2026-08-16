"""Tests for the reversible relation-reveal lens."""

from __future__ import annotations

from sase.ace.query_profile import (
    beads_query_schema,
    compile_query_profile,
    patches_query_schema,
)
from sase.ace.query_record import QueryRecord
from sase.ace.relation_reveal import (
    RelationReveal,
    build_relation_reveal_query,
    is_relation_reveal_active,
    make_relation_reveal,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationRole

_PATCH_PROFILE = compile_query_profile(patches_query_schema())
_BEADS_PROFILE = compile_query_profile(beads_query_schema())


def _target(name: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="patches", parts=("proj", name))


def test_build_relation_reveal_query_ancestor_uses_target_name() -> None:
    query = build_relation_reveal_query(
        _PATCH_PROFILE,
        RelationRole.ANCESTOR,
        origin_name="child-cl",
        target_name="parent-cl",
    )
    assert query == "ancestor:parent-cl"


def test_build_relation_reveal_query_descendant_uses_origin_name() -> None:
    query = build_relation_reveal_query(
        _PATCH_PROFILE,
        RelationRole.DESCENDANT,
        origin_name="parent-cl",
        target_name="child-cl",
    )
    assert query == "ancestor:parent-cl"


def test_build_relation_reveal_query_family_strips_revert_suffix() -> None:
    query = build_relation_reveal_query(
        _PATCH_PROFILE,
        RelationRole.FAMILY,
        origin_name="my-cl__2",
        target_name="my-cl",
    )
    assert query == "sibling:my-cl"


def test_build_relation_reveal_query_link_has_no_field() -> None:
    assert (
        build_relation_reveal_query(
            _PATCH_PROFILE,
            RelationRole.LINK,
            origin_name="a",
            target_name="b",
        )
        is None
    )


def test_build_relation_reveal_query_none_when_profile_lacks_field() -> None:
    """A pane whose profile has no ancestor/sibling field never gets a rewrite."""
    assert (
        build_relation_reveal_query(
            _BEADS_PROFILE,
            RelationRole.ANCESTOR,
            origin_name="a",
            target_name="b",
        )
        is None
    )


def test_make_relation_reveal_stamps_current_profile_digest() -> None:
    reveal = make_relation_reveal(
        pane_id="patches",
        relation="ancestors",
        role=RelationRole.ANCESTOR,
        label="Ancestors",
        origin_source="status:ready",
        origin_canonical="STATUS:ready",
        origin_target=_target("origin-cl"),
        revealed_canonical="ANCESTOR:parent-cl",
    )
    assert reveal.origin.profile_digest == _PATCH_PROFILE.digest
    assert reveal.origin.source == "status:ready"
    assert reveal.revealed_canonical == "ANCESTOR:parent-cl"


def test_is_relation_reveal_active_requires_matching_pane_and_query() -> None:
    reveal = RelationReveal(
        pane_id="patches",
        relation="ancestors",
        role=RelationRole.ANCESTOR,
        label="Ancestors",
        origin=QueryRecord(source="q", canonical="Q"),
        origin_target=_target("origin-cl"),
        revealed_canonical="ANCESTOR:parent-cl",
    )
    assert is_relation_reveal_active(
        reveal, pane_id="patches", current_canonical="ANCESTOR:parent-cl"
    )
    # A different pane never sees another pane's lens.
    assert not is_relation_reveal_active(
        reveal, pane_id="stitches", current_canonical="ANCESTOR:parent-cl"
    )
    # Once the live query moves on, the lens is inactive with no clear step.
    assert not is_relation_reveal_active(
        reveal, pane_id="patches", current_canonical="Q"
    )


def test_is_relation_reveal_active_false_when_none() -> None:
    assert not is_relation_reveal_active(
        None, pane_id="patches", current_canonical="ANCESTOR:parent-cl"
    )


def test_is_relation_reveal_active_false_when_dialect_stale() -> None:
    reveal = RelationReveal(
        pane_id="patches",
        relation="ancestors",
        role=RelationRole.ANCESTOR,
        label="Ancestors",
        origin=QueryRecord(source="q", canonical="Q", profile_digest="stale-digest"),
        origin_target=_target("origin-cl"),
        revealed_canonical="ANCESTOR:parent-cl",
    )
    assert not is_relation_reveal_active(
        reveal, pane_id="patches", current_canonical="ANCESTOR:parent-cl"
    )
