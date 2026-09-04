"""The boolean Patch dialect: sigils, macros, and predicates included."""

from __future__ import annotations

from sase.ace.query.tokenizer import STATUS_SHORTHANDS
from sase.ace.query.tokenizer import VALID_PROPERTY_KEYS as _PATCH_PROPERTY_KEYS

from ..registry import HOST_PREDICATES
from ..types import (
    ArtifactQuerySchema,
    QueryFieldSpec,
    QueryMacroSpec,
    QuerySigilSpec,
)

_PATCH_SEARCHABLE_PROPERTY_KEYS = frozenset({"status", "project", "name", "origin"})
_PATCH_PROPERTY_HINTS: dict[str, str] = {
    "status": "patch status",
    "project": "project key or display name",
    "ancestor": "patch or ancestor name",
    "name": "exact patch name",
    "sibling": "shares the same __N revert family",
    "origin": "sase, external, or unknown",
}


def patches_query_schema() -> ArtifactQuerySchema:
    """The boolean Patch dialect: sigils, macros, and predicates included."""

    property_fields = tuple(
        QueryFieldSpec(
            key=key,
            value_kind="string",
            searchable=key in _PATCH_SEARCHABLE_PROPERTY_KEYS,
            exact_match=True,
            hint=_PATCH_PROPERTY_HINTS.get(key, ""),
        )
        for key in sorted(_PATCH_PROPERTY_KEYS)
    )
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint=hint)
        for key, hint in (
            ("description", "patch description"),
            ("refs", "referenced artifact/task ids"),
            ("parent", "immediate parent patch name"),
            ("pr_url", "PR/CL url (alias cl)"),
            ("notes", "stitch, hook, comment, and mentor notes and status suffixes"),
        )
    )
    sigils = (
        QuerySigilSpec("+", "project"),
        QuerySigilSpec("^", "ancestor"),
        QuerySigilSpec("~", "sibling"),
        QuerySigilSpec("&", "name"),
    )
    macros = tuple(
        QueryMacroSpec("%", letter, "status", value)
        for letter, value in sorted(STATUS_SHORTHANDS.items())
    )
    return ArtifactQuerySchema(
        pane_id="patches",
        boolean=True,
        fields=property_fields + search_only_fields,
        sigils=sigils,
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        macros=macros,
        free_text_hint=(
            "name, description, status, origin, project, refs, parent, "
            "pr_url, notes (implicit AND)"
        ),
        identity_field="name",
    )


__all__ = ["patches_query_schema"]
