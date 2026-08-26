"""Patch-specific row coercion for :mod:`sase.ace.query.profile_evaluator`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sase.ace.query.profile_evaluator_support import (
    coerced_fields,
    coerced_fields_with_wire,
    row_wire_from_parts,
)
from sase.ace.query.profile_evaluator_types import ArtifactQueryRow
from sase.ace.query.searchable import RUNNING_AGENT_MARKER, RUNNING_PROCESS_MARKER
from sase.ace.query_profile import CompiledQueryProfile
from sase.core.patch import strip_reverted_suffix


def is_patch_row(entry: object) -> bool:
    return all(
        hasattr(entry, name)
        for name in ("name", "description", "status", "project_query_name")
    )


def coerce_patch_query_row(
    profile: CompiledQueryProfile,
    entry: object,
    *,
    ancestor_chain: tuple[str, ...] | None = None,
) -> ArtifactQueryRow:
    stable_id, raw_fields, searchable, predicates = _patch_query_row_parts(
        entry,
        ancestor_chain=ancestor_chain,
    )
    fields = coerced_fields(profile, raw_fields)
    return ArtifactQueryRow(
        stable_id=stable_id,
        fields=fields,
        searchable_text=searchable,
        predicates=predicates,
    )


def coerce_patch_query_row_with_wire(
    profile: CompiledQueryProfile,
    entry: object,
    *,
    ancestor_chain: tuple[str, ...] | None = None,
) -> tuple[ArtifactQueryRow, dict[str, Any]]:
    stable_id, raw_fields, searchable, predicates = _patch_query_row_parts(
        entry,
        ancestor_chain=ancestor_chain,
    )
    fields, wire_fields = coerced_fields_with_wire(profile, raw_fields)
    row = ArtifactQueryRow(
        stable_id=stable_id,
        fields=fields,
        searchable_text=searchable,
        predicates=predicates,
    )
    return row, row_wire_from_parts(
        wire_fields,
        searchable_text=searchable,
        predicates=predicates,
    )


def _patch_query_row_parts(
    entry: object,
    *,
    ancestor_chain: tuple[str, ...] | None,
) -> tuple[str, dict[str, Any], str, frozenset[str]]:
    from sase.ace.patch import has_any_status_suffix, normalize_pr_origin
    from sase.ace.query.matchers import get_base_status
    from sase.ace.query.searchable import get_searchable_text

    name = str(getattr(entry, "name", ""))
    parent = getattr(entry, "parent", None)
    searchable = get_searchable_text(cast(Any, entry))
    raw_fields: dict[str, Any] = {
        "status": get_base_status(str(getattr(entry, "status", ""))),
        "project": str(getattr(entry, "project_query_name", "")),
        "name": name,
        "sibling": strip_reverted_suffix(name),
        "origin": normalize_pr_origin(getattr(entry, "pr_origin", None)),
        "description": str(getattr(entry, "description", "")),
        "refs": tuple(getattr(entry, "refs", ()) or ()),
        "parent": parent or "",
        "pr_url": getattr(entry, "pr_url", "") or "",
        "notes": searchable,
    }
    if ancestor_chain is not None:
        raw_fields["ancestor"] = ancestor_chain
    elif parent:
        raw_fields["ancestor"] = (name, str(parent))
    else:
        raw_fields["ancestor"] = (name,)
    predicates = set[str]()
    if has_any_status_suffix(cast(Any, entry)):
        predicates.add("error_suffix")
    if RUNNING_AGENT_MARKER in searchable:
        predicates.add("running_agent")
    if RUNNING_PROCESS_MARKER in searchable:
        predicates.add("running_process")
    return (
        patch_query_stable_id(entry),
        raw_fields,
        searchable,
        frozenset(predicates),
    )


def patch_query_stable_id(entry: object) -> str:
    """Return the profile-query row id for a Patch-like object."""

    project = getattr(entry, "project_name", None)
    if project is None:
        project = getattr(entry, "project_query_name", "")
    return f"{project}\x1f{getattr(entry, 'name', '')}"


def patch_parent_name(entry: object) -> str | None:
    parent = getattr(entry, "parent", None)
    if parent is None:
        return None
    text = str(parent)
    return text or None


def patch_ancestor_chain(
    entry: object,
    parent_by_name: Mapping[str, str | None],
) -> tuple[str, ...]:
    """Return own name followed by transitive ancestors, cycle-guarded."""

    chain: list[str] = []
    seen: set[str] = set()
    current = str(getattr(entry, "name", ""))
    while current:
        folded = current.casefold()
        if folded in seen:
            break
        seen.add(folded)
        chain.append(current)
        parent = parent_by_name.get(folded)
        if parent is None:
            break
        current = parent
    return tuple(chain)
