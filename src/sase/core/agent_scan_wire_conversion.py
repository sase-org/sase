"""JSON-shape conversion helpers for the agent scan wire.

Split out of :mod:`sase.core.agent_scan_wire` to keep each module under the
500-line cap. Mirrors the ``wire_conversion`` / ``query_wire_conversion``
sibling pattern used elsewhere in :mod:`sase.core`.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
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
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentClanContextWire,
)
from sase.core.patch_metadata import canonicalize_patch_metadata
from sase.core.wire import known_field_kwargs


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
    payload = dict(data)
    canonicalize_patch_metadata(payload)
    return payload


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
    )


def _stats_from_dict(data: dict[str, Any]) -> AgentArtifactScanStatsWire:
    return AgentArtifactScanStatsWire(
        projects_visited=int(data.get("projects_visited", 0)),
        artifact_dirs_visited=int(data.get("artifact_dirs_visited", 0)),
        marker_files_parsed=int(data.get("marker_files_parsed", 0)),
        json_decode_errors=int(data.get("json_decode_errors", 0)),
        os_errors=int(data.get("os_errors", 0)),
        prompt_step_markers_parsed=int(data.get("prompt_step_markers_parsed", 0)),
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
            **known_field_kwargs(PendingQuestionMarkerWire, pending_question)
        )
        if isinstance(pending_question, dict)
        else None,
        workflow_state=(
            _workflow_state_from_dict(workflow_state)
            if isinstance(workflow_state, dict)
            else None
        ),
        plan_path=PlanPathMarkerWire(
            **known_field_kwargs(PlanPathMarkerWire, plan_path)
        )
        if isinstance(plan_path, dict)
        else None,
        prompt_steps=[
            PromptStepMarkerWire(**known_field_kwargs(PromptStepMarkerWire, step))
            for step in data.get("prompt_steps") or []
        ],
        raw_prompt_snippet=data.get("raw_prompt_snippet"),
        used_xprompts=[
            UsedXPromptWire(**known_field_kwargs(UsedXPromptWire, used))
            for used in data.get("used_xprompts") or []
            if isinstance(used, dict)
        ],
        has_done_marker=bool(data.get("has_done_marker", False)),
    )


def _agent_meta_from_dict(data: dict[str, Any]) -> AgentMetaWire:
    payload = canonicalize_agent_tribe_metadata(_dual_patch_name_payload(data))
    if bool(payload.get("agent_family_parallel", False)):
        if not payload.get("agent_clan"):
            payload["agent_clan"] = payload.get("agent_family")
        payload["agent_family"] = None
        payload["agent_family_role"] = None
    raw_plan_committed = payload.get("plan_committed")
    payload["plan_committed"] = (
        raw_plan_committed if type(raw_plan_committed) is bool else None
    )
    return AgentMetaWire(**known_field_kwargs(AgentMetaWire, payload))


def _done_marker_from_dict(data: dict[str, Any]) -> DoneMarkerWire:
    return DoneMarkerWire(
        **known_field_kwargs(DoneMarkerWire, _dual_patch_name_payload(data))
    )


def _running_marker_from_dict(data: dict[str, Any]) -> RunningMarkerWire:
    return RunningMarkerWire(
        **known_field_kwargs(RunningMarkerWire, _dual_patch_name_payload(data))
    )


def _waiting_marker_from_dict(data: dict[str, Any]) -> WaitingMarkerWire:
    return WaitingMarkerWire(
        **known_field_kwargs(WaitingMarkerWire, _dual_patch_name_payload(data))
    )


def _workflow_state_from_dict(data: dict[str, Any]) -> WorkflowStateWire:
    raw_steps = data.get("steps") or []
    steps = [
        WorkflowStepStateWire(**known_field_kwargs(WorkflowStepStateWire, step))
        for step in raw_steps
    ]
    payload = known_field_kwargs(WorkflowStateWire, data)
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
        records=records,
        clan_context=clan_context,
    )


__all__ = [
    "agent_artifact_index_query_to_dict",
    "agent_artifact_index_status_from_dict",
    "agent_artifact_index_update_from_dict",
    "agent_scan_wire_from_dict",
    "agent_scan_wire_to_json_dict",
]
