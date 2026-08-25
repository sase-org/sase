"""The flat Beads dialect. No sigils or macros."""

from __future__ import annotations

from sase.bead.filter_query import (
    BEAD_FILTER_TYPE_VALUES,
    BEAD_FLAG_DUE_VALUES,
    BEAD_HAS_VALUES,
    DERIVED_BEAD_STATUS_VALUES,
)
from sase.bead.model import BeadTier
from sase.bead_status_presentation import bead_status_display_order
from sase.phase_size_presentation import PHASE_SIZE_VALUES

from ..registry import HOST_PREDICATES
from ..types import ArtifactQuerySchema, QueryFieldSpec


def beads_query_schema() -> ArtifactQuerySchema:
    """The flat Beads dialect. No sigils or macros."""

    enum_fields = (
        QueryFieldSpec(
            key="type",
            value_kind="enum",
            static_values=BEAD_FILTER_TYPE_VALUES,
            repeatable=True,
            negatable=True,
            hint=", ".join(BEAD_FILTER_TYPE_VALUES),
        ),
        QueryFieldSpec(
            key="tier",
            value_kind="enum",
            static_values=tuple(value.value for value in BeadTier),
            repeatable=True,
            negatable=True,
            hint="plan or epic",
        ),
        QueryFieldSpec(
            key="status",
            value_kind="enum",
            static_values=(*bead_status_display_order(), *DERIVED_BEAD_STATUS_VALUES),
            repeatable=True,
            negatable=True,
            hint="open, closed, blocked, triage",
        ),
        QueryFieldSpec(
            key="size",
            value_kind="enum",
            static_values=PHASE_SIZE_VALUES,
            repeatable=True,
            negatable=True,
            hint="xsmall through xlarge",
        ),
        QueryFieldSpec(
            key="due",
            value_kind="enum",
            static_values=BEAD_FLAG_DUE_VALUES,
            repeatable=True,
            negatable=True,
            hint="live, soon, or due",
        ),
        QueryFieldSpec(
            key="has",
            value_kind="enum",
            static_values=BEAD_HAS_VALUES,
            repeatable=True,
            negatable=True,
            hint="+1, plan, bug, deps, notes, triage",
        ),
    )
    _exact_string_fields = frozenset({"project", "bug", "label", "task_type"})
    string_fields = tuple(
        QueryFieldSpec(
            key=key,
            repeatable=True,
            negatable=True,
            exact_match=key in _exact_string_fields,
            hint=hint,
        )
        for key, hint in (
            ("project", "project key or display name"),
            ("assignee", "assigned person or agent"),
            ("owner", "owner email or name"),
            ("model", "work model"),
            ("bug", "none, open, #42"),
            ("label", "provider issue label"),
            ("task_type", "task type slug, or untyped"),
        )
    )
    date_fields = tuple(
        QueryFieldSpec(
            key=key,
            value_kind="date",
            repeatable=True,
            negatable=True,
            hint="Nh/Nd/Nw, today, YYYY-MM-DD",
        )
        for key in ("since", "until")
    )
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint="free text")
        for key in ("id", "title", "body", "refs")
    )
    return ArtifactQuerySchema(
        pane_id="beads",
        boolean=False,
        fields=enum_fields + string_fields + date_fields + search_only_fields,
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint="id, title, body, refs (AND)",
    )


__all__ = ["beads_query_schema"]
