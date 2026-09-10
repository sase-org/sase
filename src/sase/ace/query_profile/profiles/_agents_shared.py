"""Shared field-spec builders for Agent query profiles."""

from __future__ import annotations

from collections.abc import Iterable

from ..types import QueryFieldSpec

AGENT_KIND_VALUES: tuple[str, ...] = (
    "agent",
    "member",
    "family",
    "clan",
    "workflow",
    "workflow-child",
)
AGENT_PROVIDER_VALUES: tuple[str, ...] = (
    "agy",
    "claude",
    "codex",
    "grok",
    "muse",
    "opencode",
    "qwen",
)
AGENT_CATALOG_STATE_VALUES: tuple[str, ...] = ("active", "done", "dismissed")
AGENT_CATALOG_STATUS_VALUES: tuple[str, ...] = (
    "STARTING",
    "RUNNING",
    "WAITING",
    "DONE",
    "FAILED",
    "COMPLETED",
)
AGENT_LIVE_STATUS_VALUES: tuple[str, ...] = (
    "STARTING",
    "RUNNING",
    "RETRYING",
    "ANSWERED",
    "WAITING",
    "QUEUED",
    "QUESTION",
    "WAITING INPUT",
    "PLAN",
    "TALE",
    "EPIC",
    "PLAN APPROVED",
    "TALE APPROVED",
    "EPIC APPROVED",
    "PLAN COMMITTED",
    "WORKING PLAN",
    "WORKING TALE",
    "DONE",
    "FAILED",
    "FAILED (RETRIED)",
    "COMPLETED",
    "PLAN DONE",
    "TALE DONE",
    "PLAN REJECTED",
    "EPIC CREATED",
    "STOPPED",
    "FEEDBACK",
)
AGENT_CATALOG_TRIBE_VALUES: tuple[str, ...] = ("epic", "chop", "research")
AGENT_DATE_HINT = "Nh/Nd/Nw/Nm, today, YYYY-MM-DD; Nm means months"
AGENT_DURATION_HINT = "seconds or Ns/Nm/Nh/Nd; Nm means minutes"


def agent_kind_field() -> QueryFieldSpec:
    return QueryFieldSpec(
        key="kind",
        value_kind="enum",
        static_values=AGENT_KIND_VALUES,
        hint="agent, member, family, clan, workflow, or workflow-child",
    )


def agent_status_field(
    static_values: tuple[str, ...],
    *,
    hint: str,
) -> QueryFieldSpec:
    return QueryFieldSpec(
        key="status",
        value_kind="enum",
        static_values=static_values,
        hint=hint,
    )


def agent_provider_field() -> QueryFieldSpec:
    return QueryFieldSpec(
        key="provider",
        value_kind="enum",
        static_values=AGENT_PROVIDER_VALUES,
        hint="LLM provider; static values merge with observed facets",
    )


def shared_agent_exact_string_fields() -> tuple[QueryFieldSpec, ...]:
    return (
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
    )


def shared_agent_string_fields() -> tuple[QueryFieldSpec, ...]:
    return (
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
            key="model",
            hint="model name; static values merge with observed facets",
        ),
    )


def shared_agent_bool_fields(
    extra: Iterable[tuple[str, str]] = (),
) -> tuple[QueryFieldSpec, ...]:
    return tuple(
        QueryFieldSpec(
            key=key,
            value_kind="bool",
            static_values=("true", "false"),
            hint=hint,
        )
        for key, hint in (
            ("hidden", "artifact-index hidden flag"),
            ("attention", "failed or waiting on input"),
            ("retry", "participates in a retry chain"),
            *tuple(extra),
        )
    )


def shared_agent_date_fields() -> tuple[QueryFieldSpec, ...]:
    return tuple(
        QueryFieldSpec(
            key=key,
            value_kind="date",
            hint=hint,
        )
        for key, hint in (
            ("since", f"started at or after; {AGENT_DATE_HINT}"),
            ("until", f"started at or before; {AGENT_DATE_HINT}"),
            ("after", f"finished at or after; {AGENT_DATE_HINT}"),
            ("before", f"finished at or before; {AGENT_DATE_HINT}"),
        )
    )


def shared_agent_int_fields() -> tuple[QueryFieldSpec, ...]:
    return (
        QueryFieldSpec(
            key="min",
            value_kind="int",
            hint=f"runtime at least; {AGENT_DURATION_HINT}",
        ),
        QueryFieldSpec(
            key="max",
            value_kind="int",
            hint=f"runtime at most; {AGENT_DURATION_HINT}",
        ),
        QueryFieldSpec(
            key="attempt",
            value_kind="int",
            hint="retry attempt number, equality-only",
        ),
    )


def shared_agent_text_field() -> QueryFieldSpec:
    return QueryFieldSpec(
        key="text", filterable=False, searchable=True, hint="free text"
    )


__all__ = [
    "AGENT_CATALOG_STATE_VALUES",
    "AGENT_CATALOG_STATUS_VALUES",
    "AGENT_CATALOG_TRIBE_VALUES",
    "AGENT_DATE_HINT",
    "AGENT_DURATION_HINT",
    "AGENT_KIND_VALUES",
    "AGENT_LIVE_STATUS_VALUES",
    "AGENT_PROVIDER_VALUES",
    "agent_kind_field",
    "agent_provider_field",
    "agent_status_field",
    "shared_agent_bool_fields",
    "shared_agent_date_fields",
    "shared_agent_exact_string_fields",
    "shared_agent_int_fields",
    "shared_agent_string_fields",
    "shared_agent_text_field",
]
