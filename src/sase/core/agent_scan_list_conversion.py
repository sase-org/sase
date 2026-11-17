"""JSON-shape conversion helpers for the compact agent list wire.

Split out of :mod:`sase.core.agent_scan_wire` to keep each module under the
500-line cap. Mirrors the tolerant-reader style of
:mod:`sase.core.agent_scan_wire_conversion`: unknown keys are ignored via
:func:`sase.core.wire.known_field_kwargs`, missing optional fields fall
back to dataclass defaults, and incompatible shape changes surface
through :data:`AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION`.

This decoder never calls the full-record
:func:`sase.core.agent_scan_wire_conversion._record_from_dict` and never
builds full marker dataclasses (``AgentMetaWire``, ``DoneMarkerWire``,
``RunningMarkerWire``, ``WaitingMarkerWire``, ``WorkflowStateWire``,
``PromptStepMarkerWire``). Shared nested summaries that the ``Agent``
model itself requires (``AgentSessionTurnWire``,
``FinalizerStatusSummaryWire``) and shared leaf coercions
(``created_epics_from_value``, ``wait_*_from_value``) are reused through
their public converters: they consume only compact facts and stay within
their existing caps.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.agent_scan_wire_agent_session_turn import (
    agent_session_turn_from_mapping,
)
from sase.core.agent_scan_wire_markers_epic import (
    created_epics_from_value,
    wait_epic_follows_from_value,
    wait_for_epics_of_from_value,
)
from sase.core.agent_scan_wire_markers_finalizer import (
    finalizer_status_from_mapping,
)
from sase.core.agent_scan_wire_markers_wait_turn import (
    wait_turn_bindings_from_value,
)
from sase.core.agent_scan_wire_conversion import (
    agent_artifact_index_query_to_dict as _full_query_to_dict,
)
from sase.core.agent_scan_wire_records import AgentClanContextWire
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.core.wire import known_field_kwargs

from sase.core.agent_scan_list_wire import (
    AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION,
    AgentArtifactListDoneWire,
    AgentArtifactListMetaWire,
    AgentArtifactListOutputFactsWire,
    AgentArtifactListPendingQuestionWire,
    AgentArtifactListRecordWire,
    AgentArtifactListRecoveryWire,
    AgentArtifactListRunningWire,
    AgentArtifactListSnapshotWire,
    AgentArtifactListStepWire,
    AgentArtifactListWaitingWire,
    AgentArtifactListWorkflowStepWire,
    AgentArtifactListWorkflowWire,
)

SUPPORTED_AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSIONS = frozenset(
    {AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION}
)


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _compact_turn_from_value(value: object) -> Any:
    """Decode a compact turn mapping through the shared nested reader.

    The compact turn shape is a strict subset of the nested wire shape
    (kind plus list-consumed scalars plus ``monitor``/``gate`` sub-blocks),
    so the shared tolerant reader hydrates exactly the fields the
    projection kept. Wrapping in the ``agent_session_turn`` key routes the
    mapping to the nested-shape branch instead of the flat legacy keys.
    """
    if not isinstance(value, dict):
        return None
    return agent_session_turn_from_mapping({"agent_session_turn": value})


def _canonical_tribe(value: object) -> str | None:
    """Canonicalize a compact ``tribe`` value like the full decoder.

    The Rust projection already maps the legacy ``tag`` key onto
    ``tribe``; running the same canonicalizer over the single key keeps
    the compact and full paths in agreement on invalid values.
    """
    payload: dict[str, Any] = {"tribe": value if isinstance(value, str) else None}
    canonicalize_agent_tribe_metadata(payload)
    result = payload.get("tribe")
    return result if isinstance(result, str) else None


def _output_facts_from_value(value: object) -> AgentArtifactListOutputFactsWire | None:
    if not isinstance(value, dict):
        return None
    meta = value.get("meta")
    diff_path = value.get("diff_path")
    return AgentArtifactListOutputFactsWire(
        meta=dict(meta) if isinstance(meta, dict) else {},
        diff_path=diff_path if isinstance(diff_path, str) else None,
    )


def _recovery_from_value(value: object) -> AgentArtifactListRecoveryWire | None:
    if not isinstance(value, dict):
        return None
    kwargs = known_field_kwargs(AgentArtifactListRecoveryWire, value)
    return AgentArtifactListRecoveryWire(**kwargs)


def _meta_from_dict(data: Mapping[str, Any]) -> AgentArtifactListMetaWire:
    payload = dict(data)
    kwargs = known_field_kwargs(AgentArtifactListMetaWire, payload)
    kwargs["plan_submitted_at"] = _str_list(payload.get("plan_submitted_at"))
    kwargs["retry_started_at"] = _str_list(payload.get("retry_started_at"))
    kwargs["feedback_submitted_at"] = _str_list(payload.get("feedback_submitted_at"))
    kwargs["questions_submitted_at"] = _str_list(payload.get("questions_submitted_at"))
    kwargs["wait_for"] = _str_list(payload.get("wait_for"))
    kwargs["wait_for_beads"] = _str_list(payload.get("wait_for_beads"))
    kwargs["wait_for_hoods"] = _str_list(payload.get("wait_for_hoods"))
    kwargs["wait_for_epics_of"] = wait_for_epics_of_from_value(
        payload.get("wait_for_epics_of")
    )
    kwargs["wait_epic_follows"] = wait_epic_follows_from_value(
        payload.get("wait_epic_follows")
    )
    kwargs["wait_turn_bindings"] = wait_turn_bindings_from_value(
        payload.get("wait_turn_bindings")
    )
    kwargs["created_epics"] = created_epics_from_value(payload.get("created_epics"))
    plan_committed = payload.get("plan_committed")
    kwargs["plan_committed"] = plan_committed if type(plan_committed) is bool else None
    imported_owner = payload.get("imported_source_owner")
    kwargs["imported_source_owner"] = (
        dict(imported_owner) if isinstance(imported_owner, dict) else None
    )
    auto_restart = payload.get("auto_restart")
    kwargs["auto_restart"] = (
        dict(auto_restart) if isinstance(auto_restart, dict) else None
    )
    kwargs["finalizer_status"] = finalizer_status_from_mapping(
        payload.get("finalizer_status")
    )
    kwargs["agent_session_turn"] = _compact_turn_from_value(
        payload.get("agent_session_turn")
    )
    kwargs["tribe"] = _canonical_tribe(payload.get("tribe"))
    return AgentArtifactListMetaWire(**kwargs)


def _done_from_dict(data: Mapping[str, Any]) -> AgentArtifactListDoneWire:
    payload = dict(data)
    kwargs = known_field_kwargs(AgentArtifactListDoneWire, payload)
    kwargs["step_output"] = _output_facts_from_value(payload.get("step_output"))
    imported_owner = payload.get("imported_source_owner")
    kwargs["imported_source_owner"] = (
        dict(imported_owner) if isinstance(imported_owner, dict) else None
    )
    kwargs["recovery"] = _recovery_from_value(payload.get("recovery"))
    kwargs["agent_session_turn"] = _compact_turn_from_value(
        payload.get("agent_session_turn")
    )
    return AgentArtifactListDoneWire(**kwargs)


def _waiting_from_dict(data: Mapping[str, Any]) -> AgentArtifactListWaitingWire:
    payload = dict(data)
    kwargs = known_field_kwargs(AgentArtifactListWaitingWire, payload)
    kwargs["waiting_for"] = _str_list(payload.get("waiting_for"))
    kwargs["wait_for_beads"] = _str_list(payload.get("wait_for_beads"))
    kwargs["wait_for_hoods"] = _str_list(payload.get("wait_for_hoods"))
    kwargs["wait_for_epics_of"] = wait_for_epics_of_from_value(
        payload.get("wait_for_epics_of")
    )
    kwargs["wait_epic_follows"] = wait_epic_follows_from_value(
        payload.get("wait_epic_follows")
    )
    kwargs["wait_turn_bindings"] = wait_turn_bindings_from_value(
        payload.get("wait_turn_bindings")
    )
    return AgentArtifactListWaitingWire(**kwargs)


def _workflow_step_from_dict(
    data: Mapping[str, Any],
) -> AgentArtifactListWorkflowStepWire:
    payload = dict(data)
    kwargs = known_field_kwargs(AgentArtifactListWorkflowStepWire, payload)
    kwargs["output"] = _output_facts_from_value(payload.get("output"))
    return AgentArtifactListWorkflowStepWire(**kwargs)


def _workflow_from_dict(data: Mapping[str, Any]) -> AgentArtifactListWorkflowWire:
    payload = dict(data)
    kwargs = known_field_kwargs(AgentArtifactListWorkflowWire, payload)
    kwargs["steps"] = [
        _workflow_step_from_dict(step)
        for step in payload.get("steps") or []
        if isinstance(step, dict)
    ]
    return AgentArtifactListWorkflowWire(**kwargs)


def _prompt_step_from_dict(data: Mapping[str, Any]) -> AgentArtifactListStepWire:
    payload = dict(data)
    kwargs = known_field_kwargs(AgentArtifactListStepWire, payload)
    kwargs["output"] = _output_facts_from_value(payload.get("output"))
    return AgentArtifactListStepWire(**kwargs)


def _record_from_dict(data: Mapping[str, Any]) -> AgentArtifactListRecordWire:
    """Decode one compact list record without touching full-record decoders."""
    payload = dict(data)
    meta = payload.get("meta")
    done = payload.get("done")
    running = payload.get("running")
    waiting = payload.get("waiting")
    pending_question = payload.get("pending_question")
    workflow = payload.get("workflow")
    kwargs = known_field_kwargs(AgentArtifactListRecordWire, payload)
    kwargs["meta"] = _meta_from_dict(meta) if isinstance(meta, dict) else None
    kwargs["done"] = _done_from_dict(done) if isinstance(done, dict) else None
    kwargs["running"] = (
        AgentArtifactListRunningWire(
            **known_field_kwargs(AgentArtifactListRunningWire, running)
        )
        if isinstance(running, dict)
        else None
    )
    kwargs["waiting"] = (
        _waiting_from_dict(waiting) if isinstance(waiting, dict) else None
    )
    kwargs["pending_question"] = (
        AgentArtifactListPendingQuestionWire(
            **known_field_kwargs(AgentArtifactListPendingQuestionWire, pending_question)
        )
        if isinstance(pending_question, dict)
        else None
    )
    kwargs["workflow"] = (
        _workflow_from_dict(workflow) if isinstance(workflow, dict) else None
    )
    plan_path = payload.get("plan_path")
    kwargs["plan_path"] = plan_path if isinstance(plan_path, str) else None
    kwargs["prompt_steps"] = [
        _prompt_step_from_dict(step)
        for step in payload.get("prompt_steps") or []
        if isinstance(step, dict)
    ]
    record = AgentArtifactListRecordWire(**kwargs)
    if record.record_shape != "compact":
        raise ValueError(
            f"compact list record has unexpected shape: {record.record_shape!r}"
        )
    return record


def agent_artifact_list_scan_wire_from_dict(
    data: Mapping[str, Any],
) -> AgentArtifactListSnapshotWire:
    """Rehydrate a compact list snapshot from a JSON-safe dict.

    Inverse of the Rust ``serialize_to_py`` payload shape. Missing
    optional fields fall back to dataclass defaults and unknown keys are
    dropped so a newer writer never crashes an older reader; incompatible
    shape changes surface through the list wire schema version.
    """
    payload = dict(data)
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSIONS:
        raise ValueError(
            "agent list wire schema mismatch: "
            f"got {schema_version!r}, expected one of "
            f"{sorted(SUPPORTED_AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSIONS)}"
        )
    from sase.core.agent_scan_wire_conversion import (
        agent_artifact_index_completeness_from_dict,
        agent_artifact_index_window_from_dict,
        agent_scan_options_from_dict,
        agent_scan_stats_from_dict,
    )

    records = [
        _record_from_dict(record)
        for record in payload.get("records") or []
        if isinstance(record, dict)
    ]
    clan_context = [
        AgentClanContextWire(**known_field_kwargs(AgentClanContextWire, item))
        for item in payload.get("clan_context") or []
        if isinstance(item, dict)
    ]
    return AgentArtifactListSnapshotWire(
        schema_version=int(schema_version),
        projects_root=str(payload["projects_root"]),
        options=agent_scan_options_from_dict(payload.get("options") or {}),
        stats=agent_scan_stats_from_dict(payload.get("stats") or {}),
        index_window=agent_artifact_index_window_from_dict(payload.get("index_window")),
        records=records,
        clan_context=clan_context,
        index_completeness=agent_artifact_index_completeness_from_dict(
            payload.get("index_completeness")
        ),
    )


def agent_artifact_list_records_from_dicts(
    records: Any,
) -> list[AgentArtifactListRecordWire]:
    """Rehydrate compact list records returned outside the snapshot envelope."""

    return [
        _record_from_dict(dict(record))
        for record in records or []
        if isinstance(record, dict)
    ]


def agent_artifact_list_index_query_to_dict(query: Any) -> dict[str, Any]:
    """Render a list index query through the shared full-query converter.

    The Rust list entry points reuse the existing selection pipeline and
    ignore ``record_shape`` (the response is always compact), so the query
    dict is identical to the full path's.
    """
    return _full_query_to_dict(query)


__all__ = [
    "SUPPORTED_AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSIONS",
    "agent_artifact_list_index_query_to_dict",
    "agent_artifact_list_records_from_dicts",
    "agent_artifact_list_scan_wire_from_dict",
]
