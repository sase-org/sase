"""Reversible query-rewrite lens for relation navigation.

Jumping to a relation target outside a pane's current result set has one
mechanism: rewrite the pane's query so the target is included. A
:class:`RelationReveal` gives that rewrite an identity -- the relation and
role that caused it, and the exact query it rewrote *from* -- so the host
can advertise a way back and detect when the "way back" has gone stale.

The lens is deliberately not a stored on/off flag. It is live for a pane
whenever that pane's current canonical query still equals the query the
reveal rewrote *to* and the origin dialect has not changed since; the
moment the user edits the query (their own edit, `prev_query`/`next_query`
history navigation, or a saved-query load), the live canonical query moves
away from ``revealed_canonical`` and the lens reports itself inactive with
no separate "clear" step required.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationRole

from .query_profile import CompiledQueryProfile
from .query_record import QueryRecord, current_profile_digest

#: Declared query-profile field a relation role rewrites through. A pane
#: whose profile has no field under this key cannot reveal that role's
#: targets via a query rewrite -- :func:`build_relation_reveal_query`
#: returns ``None`` rather than writing an unparseable query.
_ROLE_REVEAL_FIELDS: dict[RelationRole, str] = {
    RelationRole.ANCESTOR: "ancestor",
    RelationRole.FAMILY: "sibling",
}


@dataclass(frozen=True, slots=True)
class RelationReveal:
    """One relation-driven query rewrite, with everything needed to return."""

    pane_id: str
    relation: str
    role: RelationRole
    label: str
    origin: QueryRecord
    origin_target: ArtifactEntryTarget
    revealed_canonical: str


def build_relation_reveal_query(
    profile: CompiledQueryProfile,
    role: RelationRole,
    *,
    origin_name: str,
    target_name: str,
) -> str | None:
    """Rewrite a query to reach *target_name* through relation *role*.

    Returns ``None`` when *profile* declares no field for this relation
    instead of writing an unparseable query -- the caller reports the
    target as dangling rather than corrupting the pane's query state.

    Descendant navigation reuses the ancestor field with the *origin's*
    name ("show everything descended from here"): no pane declares a
    distinct descendant-shaped field, and a filter on "has this ancestor"
    is how the Patch dialect already expresses "is a descendant of".
    """
    field_key = _ROLE_REVEAL_FIELDS.get(
        RelationRole.ANCESTOR if role is RelationRole.DESCENDANT else role
    )
    if field_key is None or profile.field(field_key) is None:
        return None
    if role is RelationRole.DESCENDANT:
        return f"{field_key}:{origin_name}"
    if role is RelationRole.FAMILY:
        from sase.core.patch import strip_reverted_suffix

        return f"{field_key}:{strip_reverted_suffix(origin_name)}"
    return f"{field_key}:{target_name}"


def make_relation_reveal(
    *,
    pane_id: str,
    relation: str,
    role: RelationRole,
    label: str,
    origin_source: str,
    origin_canonical: str,
    origin_target: ArtifactEntryTarget,
    revealed_canonical: str,
) -> RelationReveal:
    """Build one lens record, stamping the origin dialect's digest."""
    return RelationReveal(
        pane_id=pane_id,
        relation=relation,
        role=role,
        label=label,
        origin=QueryRecord(
            source=origin_source,
            canonical=origin_canonical,
            profile_digest=current_profile_digest(pane_id),
        ),
        origin_target=origin_target,
        revealed_canonical=revealed_canonical,
    )


def is_relation_reveal_active(
    reveal: RelationReveal | None,
    *,
    pane_id: str,
    current_canonical: str,
) -> bool:
    """Return whether *reveal* is still the live lens for *pane_id*.

    ``False`` once the pane's live query has moved away from the rewrite
    (a user edit, a history navigation, or a fresh reveal) or once the
    pane's dialect has changed since the reveal was recorded.
    """
    if reveal is None or reveal.pane_id != pane_id:
        return False
    if reveal.revealed_canonical != current_canonical:
        return False
    return not reveal.origin.is_stale(pane_id)


__all__ = [
    "RelationReveal",
    "build_relation_reveal_query",
    "is_relation_reveal_active",
    "make_relation_reveal",
]
