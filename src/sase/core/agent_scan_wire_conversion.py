"""JSON-shape conversion helpers for the agent scan wire.

Split out of :mod:`sase.core.agent_scan_wire` to keep each module under the
500-line cap. Mirrors the ``wire_conversion`` / ``query_wire_conversion``
sibling pattern used elsewhere in :mod:`sase.core`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import MISSING, asdict, fields
from typing import Any

from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.core.agent_scan_wire_family_shell import family_shell_from_mapping
from sase.core.agent_scan_wire_markers import (
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    UsedXPromptWire,
    WaitingMarkerWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
)
from sase.core.agent_scan_wire_records import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexCompletenessWire,
    AgentArtifactIndexDismissalReconcileWire,
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVacuumWire,
    AgentArtifactIndexWindowWire,
    AgentArtifactRecordWire,
    AgentArtifactRecordShape,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentClanContextWire,
)
from sase.core.patch_metadata import canonicalize_patch_metadata
from sase.core.wire import known_field_kwargs


def _record_shape_from_value(value: object) -> AgentArtifactRecordShape:
    return "list" if value == "list" else "full"


def agent_scan_wire_to_json_dict(record: Any) -> Any:
    """Project an agent-scan wire record (or list of them) to a JSON-safe shape.

    Mirrors :func:`sase.core.wire.to_json_dict` but is local to this module
    so the agent-scan wire stays independent of the patch wire's
    schema bumps.
    """
    if isinstance(record, (list, tuple)):
        return [agent_scan_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: agent_scan_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def _dual_patch_name_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Populate canonical Patch names and stable legacy aliases together."""
    if data.keys().isdisjoint(_PATCH_METADATA_KEYS) or not any(
        isinstance(data.get(key), str) and data.get(key) for key in _PATCH_METADATA_KEYS
    ):
        return data
    payload = dict(data)
    canonicalize_patch_metadata(payload)
    return payload


_PATCH_METADATA_KEYS = frozenset(
    {
        "patch_name",
        "changespec_name",
        "cl_name",
        "commit_patch_name",
        "commit_changespec_name",
        "stitch_id",
        "commit_entry_id",
        "entry_id",
    }
)
_QUEUE_CAPACITY_KEYS = frozenset(
    {
        "queue_capacity",
        "queue_capacity_explicit",
        "wait_runners",
        "wait_runners_explicit",
    }
)
_resolve_authored_queue_capacity: (
    Callable[[Mapping[str, Any]], tuple[int | None, bool]] | None
) = None
_UNKNOWN_FIELD = object()
_REQUIRED_FIELD = object()
_DEFAULT_LIST = object()
_DEFAULT_DICT = object()
_FIELD_DEFAULTS: dict[type[Any], dict[str, object]] = {}


def _resolve_queue_capacity(data: Mapping[str, Any]) -> tuple[int | None, bool]:
    global _resolve_authored_queue_capacity
    if _resolve_authored_queue_capacity is None:
        from sase.xprompt.queue_directive import resolve_authored_queue_capacity

        _resolve_authored_queue_capacity = resolve_authored_queue_capacity
    return _resolve_authored_queue_capacity(data)


def _field_defaults(cls: type[Any]) -> dict[str, object]:
    defaults = _FIELD_DEFAULTS.get(cls)
    if defaults is not None:
        return defaults
    defaults = {}
    for field in fields(cls):
        if field.default is not MISSING:
            defaults[field.name] = field.default
            continue
        if field.default_factory is list:  # type: ignore[misc]
            defaults[field.name] = _DEFAULT_LIST
        elif field.default_factory is dict:  # type: ignore[misc]
            defaults[field.name] = _DEFAULT_DICT
        else:
            defaults[field.name] = _REQUIRED_FIELD
    _FIELD_DEFAULTS[cls] = defaults
    return defaults


def _non_default_field_kwargs(
    cls: type[Any],
    data: Mapping[str, Any],
) -> dict[str, Any]:
    defaults = _field_defaults(cls)
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        default = defaults.get(key, _UNKNOWN_FIELD)
        if default is _UNKNOWN_FIELD:
            continue
        if default is _REQUIRED_FIELD:
            kwargs[key] = value
            continue
        if default is _DEFAULT_LIST:
            if value == []:
                continue
        elif default is _DEFAULT_DICT:
            if value == {}:
                continue
        elif value == default:
            continue
        kwargs[key] = value
    return kwargs


def _options_from_dict(data: dict[str, Any]) -> AgentArtifactScanOptionsWire:
    return AgentArtifactScanOptionsWire(
        include_prompt_step_markers=bool(data.get("include_prompt_step_markers", True)),
        include_raw_prompt_snippets=bool(data.get("include_raw_prompt_snippets", True)),
        max_prompt_snippet_bytes=int(data.get("max_prompt_snippet_bytes", 200)),
        only_workflow_dirs=tuple(data.get("only_workflow_dirs") or ()),
        max_records=(
            None
            if data.get("max_records") is None
            else int(data.get("max_records") or 0)
        ),
        newest_first=bool(data.get("newest_first", False)),
        not_before_timestamp=data.get("not_before_timestamp"),
        include_done_markers=bool(data.get("include_done_markers", True)),
        include_workflow_state=bool(data.get("include_workflow_state", True)),
        include_waiting=bool(data.get("include_waiting", True)),
        only_projects=tuple(data.get("only_projects") or ()),
        include_project_states=tuple(data.get("include_project_states") or ()),
        capacity_only=bool(data.get("capacity_only", False)),
    )


def agent_artifact_index_query_to_dict(
    query: Any,
) -> dict[str, Any]:
    return {
        "include_active": query.include_active,
        "include_recent_completed": query.include_recent_completed,
        "include_full_history": query.include_full_history,
        "active_limit": query.active_limit,
        "recent_completed_limit": query.recent_completed_limit,
        "include_hidden": query.include_hidden,
        "freshness": query.freshness,
        "only_monitors": query.only_monitors,
        "record_shape": query.record_shape,
        "window_limit": query.window_limit,
        "candidate_filter": query.candidate_filter,
        "agents_list_projection": query.agents_list_projection,
    }


def agent_artifact_index_update_from_dict(
    data: dict[str, Any],
) -> AgentArtifactIndexUpdateWire:
    return AgentArtifactIndexUpdateWire(
        schema_version=int(data["schema_version"]),
        index_path=str(data["index_path"]),
        projects_root=str(data.get("projects_root") or ""),
        rows_indexed=int(data.get("rows_indexed", 0)),
        rows_deleted=int(data.get("rows_deleted", 0)),
        rows_skipped=int(data.get("rows_skipped", 0)),
        hidden_terminal_rows_retained=int(data.get("hidden_terminal_rows_retained", 0)),
        hidden_terminal_rows_pruned=int(data.get("hidden_terminal_rows_pruned", 0)),
    )


def agent_artifact_index_dismissal_reconcile_from_dict(
    data: dict[str, Any],
) -> AgentArtifactIndexDismissalReconcileWire:
    return AgentArtifactIndexDismissalReconcileWire(
        schema_version=int(data["schema_version"]),
        index_path=str(data["index_path"]),
        dry_run=bool(data.get("dry_run", False)),
        candidate_rows=int(data.get("candidate_rows", 0)),
        rows_backfilled=int(data.get("rows_backfilled", 0)),
        rows_already_dismissed=int(data.get("rows_already_dismissed", 0)),
        rows_skipped_live_or_unknown=int(data.get("rows_skipped_live_or_unknown", 0)),
        rows_skipped_no_dismissed_root=int(
            data.get("rows_skipped_no_dismissed_root", 0)
        ),
        rows_skipped_decode_errors=int(data.get("rows_skipped_decode_errors", 0)),
    )


def agent_artifact_index_status_from_dict(
    data: dict[str, Any],
) -> AgentArtifactIndexStatusWire:
    return AgentArtifactIndexStatusWire(
        schema_version=int(data["schema_version"]),
        index_path=str(data["index_path"]),
        agent_artifacts_rows=int(data.get("agent_artifacts_rows", 0)),
        dismissed_agents_rows=int(data.get("dismissed_agents_rows", 0)),
        agent_artifact_aliases_rows=int(data.get("agent_artifact_aliases_rows", 0)),
        agent_output_variables_rows=int(data.get("agent_output_variables_rows", 0)),
        agent_artifact_model_aliases_rows=int(
            data.get("agent_artifact_model_aliases_rows", 0)
        ),
        hidden_terminal_retention_limit=int(
            data.get("hidden_terminal_retention_limit", 0)
        ),
        hidden_terminal_rows_retained=int(data.get("hidden_terminal_rows_retained", 0)),
        hidden_terminal_rows_prunable=int(data.get("hidden_terminal_rows_prunable", 0)),
        freelist_pages=int(data.get("freelist_pages", 0)),
        freelist_bytes=int(data.get("freelist_bytes", 0)),
        file_size_bytes=int(data.get("file_size_bytes", 0)),
    )


def agent_artifact_index_vacuum_from_dict(
    data: dict[str, Any],
) -> AgentArtifactIndexVacuumWire:
    return AgentArtifactIndexVacuumWire(
        index_path=str(data["index_path"]),
        freelist_pages_before=int(data.get("freelist_pages_before", 0)),
        freelist_pages_after=int(data.get("freelist_pages_after", 0)),
        file_size_bytes_before=int(data.get("file_size_bytes_before", 0)),
        file_size_bytes_after=int(data.get("file_size_bytes_after", 0)),
        bytes_reclaimed=int(data.get("bytes_reclaimed", 0)),
    )


def _stats_from_dict(data: dict[str, Any]) -> AgentArtifactScanStatsWire:
    return AgentArtifactScanStatsWire(
        projects_visited=int(data.get("projects_visited", 0)),
        artifact_dirs_visited=int(data.get("artifact_dirs_visited", 0)),
        marker_files_parsed=int(data.get("marker_files_parsed", 0)),
        json_decode_errors=int(data.get("json_decode_errors", 0)),
        os_errors=int(data.get("os_errors", 0)),
        prompt_step_markers_parsed=int(data.get("prompt_step_markers_parsed", 0)),
        marker_signatures_checked=int(data.get("marker_signatures_checked", 0)),
        rows_repaired=int(data.get("rows_repaired", 0)),
        rows_discovered=int(data.get("rows_discovered", 0)),
        rows_removed=int(data.get("rows_removed", 0)),
        record_json_decoded=int(data.get("record_json_decoded", 0)),
    )


def _index_completeness_from_dict(
    data: dict[str, Any] | None,
) -> AgentArtifactIndexCompletenessWire | None:
    if not isinstance(data, dict):
        return None
    return AgentArtifactIndexCompletenessWire(
        complete_history=bool(data.get("complete_history", False)),
        source_reconciled=bool(data.get("source_reconciled", False)),
        rows_discovered=int(data.get("rows_discovered", 0)),
        rows_removed=int(data.get("rows_removed", 0)),
        marker_signatures_checked=int(data.get("marker_signatures_checked", 0)),
        rows_repaired=int(data.get("rows_repaired", 0)),
        record_json_decoded=int(data.get("record_json_decoded", 0)),
    )


def _index_window_from_dict(
    data: dict[str, Any] | None,
) -> AgentArtifactIndexWindowWire | None:
    if not isinstance(data, dict):
        return None
    return AgentArtifactIndexWindowWire(
        requested_limit=(
            None
            if data.get("requested_limit") is None
            else int(data.get("requested_limit") or 0)
        ),
        selected_candidate_count=int(data.get("selected_candidate_count", 0)),
        returned_record_count=int(data.get("returned_record_count", 0)),
        active_candidate_count=int(data.get("active_candidate_count", 0)),
        completed_candidate_count=int(data.get("completed_candidate_count", 0)),
        has_more=bool(data.get("has_more", False)),
        truncated=bool(data.get("truncated", False)),
    )


def _record_from_dict(data: dict[str, Any]) -> AgentArtifactRecordWire:
    agent_meta = data.get("agent_meta")
    done = data.get("done")
    running = data.get("running")
    waiting = data.get("waiting")
    pending_question = data.get("pending_question")
    workflow_state = data.get("workflow_state")
    plan_path = data.get("plan_path")
    return AgentArtifactRecordWire(
        project_name=data["project_name"],
        project_dir=data["project_dir"],
        project_file=data["project_file"],
        workflow_dir_name=data["workflow_dir_name"],
        artifact_dir=data["artifact_dir"],
        timestamp=data["timestamp"],
        agent_meta=_agent_meta_from_dict(agent_meta)
        if isinstance(agent_meta, dict)
        else None,
        done=_done_marker_from_dict(done) if isinstance(done, dict) else None,
        running=_running_marker_from_dict(running)
        if isinstance(running, dict)
        else None,
        waiting=_waiting_marker_from_dict(waiting)
        if isinstance(waiting, dict)
        else None,
        pending_question=PendingQuestionMarkerWire(
            **_non_default_field_kwargs(PendingQuestionMarkerWire, pending_question)
        )
        if isinstance(pending_question, dict)
        else None,
        workflow_state=(
            _workflow_state_from_dict(workflow_state)
            if isinstance(workflow_state, dict)
            else None
        ),
        plan_path=PlanPathMarkerWire(
            **_non_default_field_kwargs(PlanPathMarkerWire, plan_path)
        )
        if isinstance(plan_path, dict)
        else None,
        prompt_steps=[
            PromptStepMarkerWire(
                **_non_default_field_kwargs(PromptStepMarkerWire, step)
            )
            for step in data.get("prompt_steps") or []
        ],
        raw_prompt_snippet=data.get("raw_prompt_snippet"),
        used_xprompts=[
            UsedXPromptWire(**_non_default_field_kwargs(UsedXPromptWire, used))
            for used in data.get("used_xprompts") or []
            if isinstance(used, dict)
        ],
        has_done_marker=bool(data.get("has_done_marker", False)),
        record_shape=_record_shape_from_value(data.get("record_shape")),
    )


def _agent_meta_from_dict(data: dict[str, Any]) -> AgentMetaWire:
    payload = _queue_capacity_alias_payload(_dual_patch_name_payload(data))
    if "tag" in payload or isinstance(payload.get("tribe"), str):
        payload = canonicalize_agent_tribe_metadata(dict(payload))
    kwargs = _non_default_field_kwargs(AgentMetaWire, payload)
    if bool(payload.get("agent_family_parallel", False)):
        if not kwargs.get("agent_clan"):
            kwargs["agent_clan"] = payload.get("agent_family")
        kwargs["agent_family"] = None
        kwargs["agent_family_role"] = None
    if "plan_committed" in payload and type(payload.get("plan_committed")) is not bool:
        kwargs["plan_committed"] = None
    family_shell = family_shell_from_mapping(payload)
    if family_shell is not None:
        kwargs["family_shell"] = family_shell
    return AgentMetaWire(**kwargs)


def _done_marker_from_dict(data: dict[str, Any]) -> DoneMarkerWire:
    payload = _dual_patch_name_payload(data)
    kwargs = _non_default_field_kwargs(DoneMarkerWire, payload)
    family_shell = family_shell_from_mapping(payload)
    if family_shell is not None:
        kwargs["family_shell"] = family_shell
    return DoneMarkerWire(**kwargs)


def _running_marker_from_dict(data: dict[str, Any]) -> RunningMarkerWire:
    return RunningMarkerWire(
        **_non_default_field_kwargs(RunningMarkerWire, _dual_patch_name_payload(data))
    )


def _waiting_marker_from_dict(data: dict[str, Any]) -> WaitingMarkerWire:
    return WaitingMarkerWire(
        **_non_default_field_kwargs(
            WaitingMarkerWire,
            _queue_capacity_alias_payload(_dual_patch_name_payload(data)),
        )
    )


def _queue_capacity_alias_payload(data: dict[str, Any]) -> dict[str, Any]:
    if data.keys().isdisjoint(_QUEUE_CAPACITY_KEYS) or (
        data.get("queue_capacity") is None
        and data.get("wait_runners") is None
        and not data.get("queue_capacity_explicit")
        and not data.get("wait_runners_explicit")
    ):
        return data
    payload = dict(data)

    capacity, explicit = _resolve_queue_capacity(payload)
    payload["queue_capacity"] = capacity
    payload["queue_capacity_explicit"] = explicit
    payload["wait_runners"] = capacity
    payload["wait_runners_explicit"] = explicit
    return payload


def _workflow_state_from_dict(data: dict[str, Any]) -> WorkflowStateWire:
    raw_steps = data.get("steps") or []
    steps = [
        WorkflowStepStateWire(**_non_default_field_kwargs(WorkflowStepStateWire, step))
        for step in raw_steps
    ]
    payload = _non_default_field_kwargs(WorkflowStateWire, data)
    payload.pop("steps", None)
    return WorkflowStateWire(steps=steps, **payload)


def agent_scan_wire_from_dict(data: dict[str, Any]) -> AgentArtifactScanWire:
    """Rehydrate an :class:`AgentArtifactScanWire` from a JSON-safe dict.

    Inverse of :func:`agent_scan_wire_to_json_dict`. Used by the facade's
    Rust adapter (the PyO3 binding returns plain Python dicts/lists) and
    by tests that round-trip the snapshot through JSON.

    Missing optional fields fall back to dataclass defaults, and unknown
    keys are dropped via :func:`sase.core.wire.known_field_kwargs` so a
    newer writer (Rust core or marker files from a newer sase) never
    crashes an older reader; incompatible shape changes surface through
    the wire schema version, not constructor ``TypeError``.
    """
    schema_version = int(data["schema_version"])
    if schema_version != AGENT_SCAN_WIRE_SCHEMA_VERSION:
        raise ValueError(
            "agent scan wire schema mismatch: "
            f"got {schema_version}, expected {AGENT_SCAN_WIRE_SCHEMA_VERSION}"
        )
    options = _options_from_dict(data.get("options") or {})
    stats = _stats_from_dict(data.get("stats") or {})
    records = [_record_from_dict(r) for r in data.get("records") or []]
    clan_context = [
        AgentClanContextWire(**known_field_kwargs(AgentClanContextWire, item))
        for item in data.get("clan_context") or []
        if isinstance(item, dict)
    ]
    return AgentArtifactScanWire(
        schema_version=schema_version,
        projects_root=data["projects_root"],
        options=options,
        stats=stats,
        index_window=_index_window_from_dict(data.get("index_window")),
        records=records,
        clan_context=clan_context,
        index_completeness=_index_completeness_from_dict(
            data.get("index_completeness")
        ),
    )


def agent_artifact_records_from_dicts(
    records: Sequence[Mapping[str, Any]],
) -> list[AgentArtifactRecordWire]:
    """Rehydrate artifact records returned outside the scanner envelope."""

    return [_record_from_dict(dict(record)) for record in records]


__all__ = [
    "agent_artifact_records_from_dicts",
    "agent_artifact_index_dismissal_reconcile_from_dict",
    "agent_artifact_index_query_to_dict",
    "agent_artifact_index_status_from_dict",
    "agent_artifact_index_update_from_dict",
    "agent_scan_wire_from_dict",
    "agent_scan_wire_to_json_dict",
]
