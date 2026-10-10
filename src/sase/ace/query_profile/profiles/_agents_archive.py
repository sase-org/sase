"""The boolean agents-archive dialect. No sigils, shorthands, or predicates."""

from __future__ import annotations

from sase.sdd.artifact_link_store import assembled_artifact_relations

from ..types import ArtifactQuerySchema, QueryFieldSpec
from ._agents_shared import (
    AGENT_CATALOG_TRIBE_VALUES,
    AGENT_LIVE_STATUS_VALUES,
    agent_kind_field,
    agent_provider_field,
    agent_status_field,
    shared_agent_date_fields,
    shared_agent_exact_string_fields,
    shared_agent_int_fields,
    shared_agent_string_fields,
)

_ARCHIVE_OUTCOME_VALUES: tuple[str, ...] = ("done", "failed", "interrupted")


def agents_archive_query_schema() -> ArtifactQuerySchema:
    """The boolean agents-archive dialect."""

    enum_fields = (
        agent_kind_field(),
        agent_status_field(
            AGENT_LIVE_STATUS_VALUES,
            hint="stored status on the archived run",
        ),
        agent_provider_field(),
        QueryFieldSpec(
            key="outcome",
            value_kind="enum",
            static_values=_ARCHIVE_OUTCOME_VALUES,
            hint="done, failed, or interrupted",
        ),
        QueryFieldSpec(
            key="clan_tribe",
            value_kind="enum",
            static_values=AGENT_CATALOG_TRIBE_VALUES,
            hint="clan tribe: epic, chop, or research",
        ),
        QueryFieldSpec(
            key="relation",
            value_kind="enum",
            static_values=_agent_relation_values(),
            hint="artifact-link relation slug",
        ),
    )
    exact_string_fields = (
        *shared_agent_exact_string_fields(),
        QueryFieldSpec(
            key="tribe",
            exact_match=True,
            hint="user-defined live tribe",
        ),
        QueryFieldSpec(
            key="tab",
            exact_match=True,
            hint="stored tab names, or main for the default tab",
        ),
        QueryFieldSpec(
            key="artifact",
            exact_match=True,
            hint="canonical artifact ref linked to the agent",
        ),
    )
    bool_fields = (
        QueryFieldSpec(
            key="retry",
            value_kind="bool",
            static_values=("true", "false"),
            hint="participates in a retry chain",
        ),
        QueryFieldSpec(
            key="restorable",
            value_kind="bool",
            static_values=("true", "false"),
            hint="durably revivable with a bundle path on disk",
        ),
        QueryFieldSpec(
            key="linked",
            value_kind="bool",
            static_values=("true", "false"),
            hint="true when at least one artifact link touches the agent",
        ),
    )
    return ArtifactQuerySchema(
        pane_id="agents-archive",
        boolean=True,
        fields=(
            enum_fields
            + exact_string_fields
            + shared_agent_string_fields()
            + bool_fields
            + shared_agent_date_fields()
            + shared_agent_int_fields()
        ),
        predicates=(),
        any_special=False,
        free_text_hint="name (implicit AND)",
        identity_field="name",
    )


def _agent_relation_values() -> tuple[str, ...]:
    return tuple(
        slug
        for relation in assembled_artifact_relations()
        if (slug := str(relation.get("slug") or "").strip())
    )


__all__ = ["agents_archive_query_schema"]
