"""The flat Plans dialect. No sigils or macros."""

from __future__ import annotations

from ..registry import HOST_PREDICATES
from ..types import ArtifactQuerySchema, QueryFieldSpec


def plans_query_schema() -> ArtifactQuerySchema:
    """The flat Plans dialect. No sigils or macros.

    None of ``kind``/``status``/``tier`` are enum-validated today (unlike
    the equivalent Beads keys), so they compile as plain strings even though
    the filter bar offers static completion hints for them.
    """

    string_fields = tuple(
        QueryFieldSpec(
            key=key,
            repeatable=True,
            negatable=True,
            exact_match=True,
            searchable=key == "path",
            hint=hint,
        )
        for key, hint in (
            ("kind", "proposal, active, archive, plans, research"),
            ("status", "proposed or plan frontmatter status"),
            ("tier", "tale, epic, plan"),
            ("project", "project key or display name"),
            ("path", "document path or provider identity"),
        )
    )
    date_fields = tuple(
        QueryFieldSpec(key=key, value_kind="date", hint="Nh/Nd/Nw, today, YYYY-MM-DD")
        for key in ("since", "until")
    )
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint="free text")
        for key in ("title", "body")
    )
    return ArtifactQuerySchema(
        pane_id="ref:plan",
        boolean=False,
        fields=string_fields + date_fields + search_only_fields,
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint="title, body, path (AND)",
        identity_field="path",
    )


__all__ = ["plans_query_schema"]
