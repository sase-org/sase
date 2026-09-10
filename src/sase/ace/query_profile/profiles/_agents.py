"""The boolean Artifacts Agent pane dialect. No sigils or macros."""

from __future__ import annotations

from sase.sdd.artifact_link_store import assembled_artifact_relations

from ..registry import HOST_PREDICATES
from ..types import ArtifactQuerySchema, QueryFieldSpec
from ._agents_shared import (
    AGENT_CATALOG_STATE_VALUES,
    AGENT_CATALOG_STATUS_VALUES,
    AGENT_CATALOG_TRIBE_VALUES,
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


def agents_query_schema() -> ArtifactQuerySchema:
    """The boolean Artifacts Agent pane dialect. No sigils or macros."""

    relation_values = _agent_relation_values()
    enum_fields = (
        agent_kind_field(),
        QueryFieldSpec(
            key="tribe",
            value_kind="enum",
            static_values=AGENT_CATALOG_TRIBE_VALUES,
            hint="clan tribe: epic, chop, or research",
        ),
        QueryFieldSpec(
            key="state",
            value_kind="enum",
            static_values=AGENT_CATALOG_STATE_VALUES,
            hint="active, done, or dismissed",
        ),
        agent_status_field(
            AGENT_CATALOG_STATUS_VALUES,
            hint="STARTING, RUNNING, WAITING, DONE, FAILED, or COMPLETED",
        ),
        agent_provider_field(),
        QueryFieldSpec(
            key="relation",
            value_kind="enum",
            static_values=relation_values,
            hint="artifact-link relation slug",
        ),
    )
    exact_string_fields = (
        *shared_agent_exact_string_fields(),
        QueryFieldSpec(
            key="artifact",
            exact_match=True,
            hint="canonical artifact ref linked to the agent",
        ),
    )
    string_fields = (
        *shared_agent_string_fields(),
        QueryFieldSpec(
            key="parent",
            hint="parent timestamp",
        ),
    )
    bool_fields = shared_agent_bool_fields(
        (
            ("dismissed", "true when state is dismissed"),
            ("revivable", "dismissed with durable archive inputs"),
            ("historically_viewable", "archive has enough data to inspect"),
            ("durably_revivable", "archive has enough data to restore"),
            ("restartable", "archive has prompt and model parameters"),
            ("linked", "true when at least one artifact link touches the agent"),
        )
    )
    date_fields = shared_agent_date_fields()
    int_fields = shared_agent_int_fields()
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint="free text")
        for key in ("label",)
    )
    return ArtifactQuerySchema(
        pane_id="agents",
        boolean=True,
        fields=(
            enum_fields
            + exact_string_fields
            + string_fields
            + bool_fields
            + date_fields
            + int_fields
            + search_only_fields
            + (shared_agent_text_field(),)
        ),
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint="name, label, text metadata (implicit AND)",
        identity_field="name",
    )


def _agent_relation_values() -> tuple[str, ...]:
    return tuple(
        slug
        for relation in assembled_artifact_relations()
        if (slug := str(relation.get("slug") or "").strip())
    )


__all__ = ["agents_query_schema"]
