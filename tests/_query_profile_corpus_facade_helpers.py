"""Shared fixtures for query profile corpus facade tests."""

from __future__ import annotations

from sase.ace.query_profile import ArtifactQuerySchema, QueryFieldSpec

_BEADS_ROWS = [
    {
        "stable_id": "open-task",
        "fields": {
            "type": "task",
            "status": "open",
            "project": "sase",
            "assignee": "Alice Smith",
            "title": "Load filter profile",
            "body": "Reference evaluator",
        },
    },
    {
        "stable_id": "closed-phase",
        "fields": {
            "type": "phase",
            "status": "closed",
            "project": "sase",
            "assignee": "Bob",
            "title": "Load filter profile",
            "body": "Reference evaluator",
        },
    },
    {
        "stable_id": "open-plan",
        "fields": {
            "type": "plan",
            "status": "open",
            "project": "sase",
            "assignee": "Carol",
            "title": "Unrelated",
            "body": "Reference evaluator",
        },
    },
]


def _flags_query_schema() -> ArtifactQuerySchema:
    return ArtifactQuerySchema(
        pane_id="flags",
        boolean=False,
        fields=(
            QueryFieldSpec(key="flag", value_kind="bool", negatable=True),
            QueryFieldSpec(key="title", filterable=False, searchable=True),
        ),
    )


def _bounds_query_schema() -> ArtifactQuerySchema:
    return ArtifactQuerySchema(
        pane_id="bounds",
        boolean=False,
        fields=(
            QueryFieldSpec(key="after", value_kind="date"),
            QueryFieldSpec(key="before", value_kind="date"),
            QueryFieldSpec(key="since", value_kind="date"),
            QueryFieldSpec(key="until", value_kind="date"),
            QueryFieldSpec(key="created", value_kind="date"),
            QueryFieldSpec(key="min", value_kind="int"),
            QueryFieldSpec(key="max", value_kind="int"),
            QueryFieldSpec(key="exit", value_kind="int"),
        ),
    )


def _boolean_value_query_schema() -> ArtifactQuerySchema:
    return ArtifactQuerySchema(
        pane_id="values",
        boolean=True,
        fields=(
            QueryFieldSpec(key="name", exact_match=True, searchable=True),
            QueryFieldSpec(key="family", exact_match=True),
            QueryFieldSpec(key="since", value_kind="date"),
            QueryFieldSpec(key="until", value_kind="date"),
            QueryFieldSpec(key="min", value_kind="int"),
            QueryFieldSpec(key="attempt", value_kind="int"),
            QueryFieldSpec(key="body", filterable=False, searchable=True),
        ),
    )
