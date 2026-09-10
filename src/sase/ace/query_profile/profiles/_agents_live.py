"""The boolean live Agents tab dialect. No sigils, macros, or predicates."""

from __future__ import annotations

from ..types import ArtifactQuerySchema, QueryFieldSpec
from ._agents_shared import (
    AGENT_LIVE_STATUS_VALUES,
    agent_kind_field,
    agent_provider_field,
    agent_status_field,
    shared_agent_bool_fields,
    shared_agent_date_fields,
    shared_agent_exact_string_fields,
    shared_agent_int_fields,
    shared_agent_string_fields,
    shared_agent_text_field,
)


def agents_live_query_schema() -> ArtifactQuerySchema:
    """The boolean live Agents tab dialect."""

    enum_fields = (
        agent_kind_field(),
        agent_status_field(
            AGENT_LIVE_STATUS_VALUES,
            hint="live Agents tab status; static values merge with observed facets",
        ),
        agent_provider_field(),
        QueryFieldSpec(
            key="needs",
            value_kind="enum",
            static_values=("input",),
            hint="input",
        ),
        QueryFieldSpec(
            key="source",
            value_kind="enum",
            static_values=("axe", "manual"),
            hint="axe or manual",
        ),
    )
    live_string_fields = (
        QueryFieldSpec(
            key="cl",
            searchable=True,
            hint="Patch name / change label",
        ),
        QueryFieldSpec(
            key="machine",
            exact_match=True,
            hint="machine alias or hostname; local rows are here",
        ),
        QueryFieldSpec(
            key="tribe",
            exact_match=True,
            hint="user-defined live tribe",
        ),
    )
    live_bool_fields = shared_agent_bool_fields(
        (
            ("pinned", "true when assigned to the pinned tribe"),
            ("unread", "true when completion is unread"),
        )
    )
    return ArtifactQuerySchema(
        pane_id="agents-live",
        boolean=True,
        fields=(
            enum_fields
            + shared_agent_exact_string_fields()
            + shared_agent_string_fields()
            + live_string_fields
            + live_bool_fields
            + shared_agent_date_fields()
            + shared_agent_int_fields()
            + (shared_agent_text_field(),)
        ),
        predicates=(),
        any_special=False,
        free_text_hint="name, cl, text metadata (implicit AND)",
        identity_field="name",
    )


__all__ = ["agents_live_query_schema"]
