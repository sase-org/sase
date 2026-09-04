"""The boolean Artifacts Agent pane dialect. No sigils or macros."""

from __future__ import annotations

from sase.sdd.artifact_link_store import assembled_artifact_relations

from ..registry import HOST_PREDICATES
from ..types import ArtifactQuerySchema, QueryFieldSpec

_AGENT_KIND_VALUES: tuple[str, ...] = (
    "agent",
    "member",
    "family",
    "clan",
    "workflow",
    "workflow-child",
)
_AGENT_PROVIDER_VALUES: tuple[str, ...] = (
    "agy",
    "claude",
    "codex",
    "grok",
    "muse",
    "opencode",
    "qwen",
)
_AGENT_STATE_VALUES: tuple[str, ...] = ("active", "done", "dismissed")
_AGENT_STATUS_VALUES: tuple[str, ...] = (
    "STARTING",
    "RUNNING",
    "WAITING",
    "DONE",
    "FAILED",
    "COMPLETED",
)
_AGENT_TRIBE_VALUES: tuple[str, ...] = ("epic", "chop", "research")
_AGENT_DATE_HINT = "Nh/Nd/Nw/Nm, today, YYYY-MM-DD; Nm means months"
_AGENT_DURATION_HINT = "seconds or Ns/Nm/Nh/Nd; Nm means minutes"


def agents_query_schema() -> ArtifactQuerySchema:
    """The boolean Artifacts Agent pane dialect. No sigils or macros."""

    relation_values = _agent_relation_values()
    enum_fields = (
        QueryFieldSpec(
            key="kind",
            value_kind="enum",
            static_values=_AGENT_KIND_VALUES,
            hint="agent, member, family, clan, workflow, or workflow-child",
        ),
        QueryFieldSpec(
            key="tribe",
            value_kind="enum",
            static_values=_AGENT_TRIBE_VALUES,
            hint="clan tribe: epic, chop, or research",
        ),
        QueryFieldSpec(
            key="state",
            value_kind="enum",
            static_values=_AGENT_STATE_VALUES,
            hint="active, done, or dismissed",
        ),
        QueryFieldSpec(
            key="status",
            value_kind="enum",
            static_values=_AGENT_STATUS_VALUES,
            hint="STARTING, RUNNING, WAITING, DONE, FAILED, or COMPLETED",
        ),
        QueryFieldSpec(
            key="provider",
            value_kind="enum",
            static_values=_AGENT_PROVIDER_VALUES,
            hint="LLM provider; static values merge with observed facets",
        ),
        QueryFieldSpec(
            key="relation",
            value_kind="enum",
            static_values=relation_values,
            hint="artifact-link relation slug",
        ),
    )
    exact_string_fields = (
        QueryFieldSpec(
            key="name",
            exact_match=True,
            searchable=True,
            hint="agent name or canonical global name",
        ),
        QueryFieldSpec(
            key="family",
            exact_match=True,
            hint="family name derived from the agent name",
        ),
        QueryFieldSpec(
            key="clan",
            exact_match=True,
            hint="clan name or agent_clan",
        ),
        QueryFieldSpec(
            key="project",
            exact_match=True,
            hint="project key or display name",
        ),
        QueryFieldSpec(
            key="artifact",
            exact_match=True,
            hint="canonical artifact ref linked to the agent",
        ),
    )
    string_fields = (
        QueryFieldSpec(
            key="role",
            static_values=("code", "plan", "mon"),
            hint="member role suffix such as code, plan, or mon",
        ),
        QueryFieldSpec(
            key="workflow",
            hint="workflow name",
        ),
        QueryFieldSpec(
            key="parent",
            hint="parent timestamp",
        ),
        QueryFieldSpec(
            key="model",
            hint="model name; static values merge with observed facets",
        ),
    )
    bool_fields = tuple(
        QueryFieldSpec(
            key=key,
            value_kind="bool",
            static_values=("true", "false"),
            hint=hint,
        )
        for key, hint in (
            ("hidden", "artifact-index hidden flag"),
            ("dismissed", "true when state is dismissed"),
            ("revivable", "dismissed with durable archive inputs"),
            ("historically_viewable", "archive has enough data to inspect"),
            ("durably_revivable", "archive has enough data to restore"),
            ("restartable", "archive has prompt and model parameters"),
            ("attention", "failed or waiting on input"),
            ("retry", "participates in a retry chain"),
            ("linked", "true when at least one artifact link touches the agent"),
        )
    )
    date_fields = tuple(
        QueryFieldSpec(
            key=key,
            value_kind="date",
            hint=hint,
        )
        for key, hint in (
            ("since", f"started at or after; {_AGENT_DATE_HINT}"),
            ("until", f"started at or before; {_AGENT_DATE_HINT}"),
            ("after", f"finished at or after; {_AGENT_DATE_HINT}"),
            ("before", f"finished at or before; {_AGENT_DATE_HINT}"),
        )
    )
    int_fields = (
        QueryFieldSpec(
            key="min",
            value_kind="int",
            hint=f"runtime at least; {_AGENT_DURATION_HINT}",
        ),
        QueryFieldSpec(
            key="max",
            value_kind="int",
            hint=f"runtime at most; {_AGENT_DURATION_HINT}",
        ),
        QueryFieldSpec(
            key="attempt",
            value_kind="int",
            hint="retry attempt number, equality-only",
        ),
    )
    search_only_fields = tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint="free text")
        for key in ("label", "text")
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
