"""Agent artifact record helpers for episode collection."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path
from typing import Any, cast

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)
from sase.memory.episodes._collector_utils import (
    compact_timestamp,
    read_json_object,
    str_list,
    str_value,
    timestamp_dir_to_iso,
    unique_strings,
)
from sase.memory.episodes.source_refs import normalize_source_path


def record_agent_names(record: AgentArtifactRecordWire) -> list[str]:
    trace = _record_trace(record)
    values = [
        str_value(trace.get("agent_name")),
        record.agent_meta.name if record.agent_meta is not None else None,
        record.done.name if record.done is not None else None,
    ]
    return unique_strings(values)


def record_display_name(record: AgentArtifactRecordWire) -> str:
    names = record_agent_names(record)
    return names[0] if names else record.timestamp


def record_family(record: AgentArtifactRecordWire) -> str | None:
    trace = _record_trace(record)
    trace_family = str_value(trace.get("agent_family")) or str_value(
        trace.get("workflow_name")
    )
    if trace_family is not None:
        return trace_family
    meta = record.agent_meta
    if meta is None:
        return None
    return meta.agent_family or meta.workflow_name


def record_role_suffix(record: AgentArtifactRecordWire) -> str | None:
    trace = _record_trace(record)
    trace_role = str_value(trace.get("role_suffix")) or str_value(
        trace.get("agent_role")
    )
    if trace_role is not None:
        return trace_role
    meta = record.agent_meta
    if meta is None:
        return None
    return meta.role_suffix or meta.agent_family_role


def record_changespec_names(record: AgentArtifactRecordWire) -> list[str]:
    trace = _record_trace(record)
    meta = record.agent_meta
    done = record.done
    values = [
        *str_list(trace.get("changespec_names")),
        str_value(trace.get("changespec_name")),
        meta.changespec_name if meta is not None else None,
        meta.cl_name if meta is not None else None,
        meta.commit_changespec_name if meta is not None else None,
        done.cl_name if done is not None else None,
    ]
    return unique_strings(values)


def record_bead_ids(record: AgentArtifactRecordWire) -> list[str]:
    trace = _record_trace(record)
    meta = record.agent_meta
    values: list[str | None] = [
        *str_list(trace.get("bead_ids")),
        str_value(trace.get("bead_id")),
    ]
    if meta is None:
        return unique_strings(values)
    values.extend(
        [
            meta.bead_id,
            meta.epic_bead_id,
            meta.phase_bead_id,
            meta.legend_bead_id,
        ]
    )
    return unique_strings(values)


def record_related_timestamps(
    record: AgentArtifactRecordWire,
) -> Iterator[tuple[str, str]]:
    trace = _record_trace(record)
    for kind, timestamp in (
        ("parent_agent", str_value(trace.get("parent_timestamp"))),
        ("parent_agent", str_value(trace.get("parent_agent_timestamp"))),
        ("root_agent", str_value(trace.get("root_timestamp"))),
        ("retry_of", str_value(trace.get("retry_of_timestamp"))),
        ("retry_root", str_value(trace.get("retry_chain_root_timestamp"))),
        ("retried_as", str_value(trace.get("retried_as_timestamp"))),
    ):
        if timestamp:
            yield kind, compact_timestamp(timestamp)

    meta = record.agent_meta
    done = record.done
    if meta is not None:
        for kind, timestamp in (
            ("parent_agent", meta.parent_timestamp),
            ("parent_agent", meta.parent_agent_timestamp),
            ("retry_of", meta.retry_of_timestamp),
            ("retry_root", meta.retry_chain_root_timestamp),
            ("retried_as", meta.retried_as_timestamp),
        ):
            if timestamp:
                yield kind, compact_timestamp(timestamp)
    if done is not None:
        for kind, timestamp in (
            ("retry_root", done.retry_chain_root_timestamp),
            ("retried_as", done.retried_as_timestamp),
        ):
            if timestamp:
                yield kind, compact_timestamp(timestamp)


def record_chat_paths(
    record: AgentArtifactRecordWire,
    raw_meta: dict[str, Any],
) -> list[str]:
    trace = _record_trace(record)
    paths: list[str | None] = [
        str_value(trace.get("chat_path")),
        record.done.response_path if record.done is not None else None,
        str_value(raw_meta.get("chat_path")),
    ]
    paths.extend(str_list(trace.get("chat_paths")))
    paths.extend(step.response_path for step in record.prompt_steps)
    return unique_strings(paths)


def record_referenced_paths(
    record: AgentArtifactRecordWire,
    raw_meta: dict[str, Any],
    raw_done: dict[str, Any],
) -> list[tuple[str, str, str]]:
    trace = _record_trace(record)
    meta = record.agent_meta
    done = record.done
    paths: list[tuple[str | None, str, str]] = [
        (str_value(trace.get("plan_path")), "plan", "plan"),
        (str_value(trace.get("sdd_prompt_path")), "plan", "plan"),
        (str_value(trace.get("sdd_plan_path")), "plan", "plan"),
        (
            str_value(trace.get("question_request_path")),
            "question",
            "question",
        ),
        (
            str_value(trace.get("question_response_path")),
            "question",
            "question",
        ),
        (
            record.plan_path.plan_path if record.plan_path is not None else None,
            "plan",
            "plan",
        ),
        (meta.plan_path if meta is not None else None, "plan", "plan"),
        (meta.sdd_prompt_path if meta is not None else None, "plan", "plan"),
        (meta.sdd_plan_path if meta is not None else None, "plan", "plan"),
        (
            meta.question_request_path if meta is not None else None,
            "question",
            "question",
        ),
        (
            meta.question_response_path if meta is not None else None,
            "question",
            "question",
        ),
        (meta.commit_diff_path if meta is not None else None, "artifact", "diff"),
        (done.plan_path if done is not None else None, "plan", "plan"),
        (done.diff_path if done is not None else None, "artifact", "diff"),
        (done.output_path if done is not None else None, "artifact", "output"),
        (str_value(raw_meta.get("chat_path")), "chat", "response_chat"),
        (
            str_value(raw_meta.get("memory_reads_path")),
            "memory_read",
            "memory_context",
        ),
        (
            str_value(raw_done.get("memory_reads_path")),
            "memory_read",
            "memory_context",
        ),
    ]
    if done is not None:
        paths.extend((path, "image", "artifact") for path in done.image_paths)
        paths.extend((path, "pdf", "artifact") for path in done.markdown_pdf_paths)
    paths.extend(
        (path, "feedback", "feedback") for path in str_list(trace.get("feedback_paths"))
    )
    paths.extend(
        (path, "question", "question") for path in str_list(trace.get("qa_paths"))
    )
    for key in ("source_paths", "artifact_paths"):
        paths.extend(
            (path, "artifact", "artifact") for path in str_list(raw_done.get(key))
        )
        paths.extend(
            (path, "artifact", "artifact") for path in str_list(raw_meta.get(key))
        )
    return [
        (path, kind, edge_kind)
        for path, kind, edge_kind in paths
        if path is not None and path
    ]


def record_started_timestamp(record: AgentArtifactRecordWire) -> str | None:
    trace = _record_trace(record)
    trace_started = str_value(trace.get("run_started_at"))
    if trace_started:
        return trace_started
    meta = record.agent_meta
    if meta is not None and meta.run_started_at:
        return meta.run_started_at
    trace_timestamp = str_value(trace.get("artifact_timestamp"))
    if trace_timestamp:
        return timestamp_dir_to_iso(compact_timestamp(trace_timestamp))
    return timestamp_dir_to_iso(record.timestamp)


def _record_trace(record: AgentArtifactRecordWire) -> dict[str, Any]:
    return read_json_object(Path(record.artifact_dir) / "episode_trace.json")


def record_from_artifact_dir(
    artifact_dir: Path,
    projects_root: Path,
) -> AgentArtifactRecordWire:
    project_name, workflow_name = _project_workflow_from_artifact_dir(
        artifact_dir,
        projects_root,
    )
    agent_meta = _marker_from_json(AgentMetaWire, artifact_dir / "agent_meta.json")
    done = _marker_from_json(DoneMarkerWire, artifact_dir / "done.json")
    running = _marker_from_json(RunningMarkerWire, artifact_dir / "running.json")
    waiting = _marker_from_json(WaitingMarkerWire, artifact_dir / "waiting.json")
    pending = _marker_from_json(
        PendingQuestionMarkerWire,
        artifact_dir / "pending_question.json",
    )
    workflow_state = _marker_from_json(
        WorkflowStateWire,
        artifact_dir / "workflow_state.json",
    )
    plan_path = _marker_from_json(PlanPathMarkerWire, artifact_dir / "plan_path.json")
    prompt_steps = [
        marker
        for marker in (
            _marker_from_json(PromptStepMarkerWire, path)
            for path in sorted(artifact_dir.glob("prompt_step_*.json"))
        )
        if marker is not None
    ]
    project_dir = projects_root / project_name
    return AgentArtifactRecordWire(
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{project_name}.sase"),
        workflow_dir_name=workflow_name,
        artifact_dir=str(artifact_dir),
        timestamp=artifact_dir.name,
        agent_meta=agent_meta,
        done=done,
        running=running,
        waiting=waiting,
        pending_question=pending,
        workflow_state=workflow_state,
        plan_path=plan_path,
        prompt_steps=prompt_steps,
        raw_prompt_snippet=None,
        has_done_marker=(artifact_dir / "done.json").exists(),
    )


def _marker_from_json[MarkerT](cls: type[MarkerT], path: Path) -> MarkerT | None:
    data = read_json_object(path)
    if not data:
        return None
    allowed = {field.name for field in fields(cast(Any, cls))}
    filtered = {key: value for key, value in data.items() if key in allowed}
    if cls is PromptStepMarkerWire and "file_name" not in filtered:
        filtered["file_name"] = path.name
    try:
        return cls(**filtered)
    except TypeError:
        return None


def _project_workflow_from_artifact_dir(
    artifact_dir: Path,
    projects_root: Path,
) -> tuple[str, str]:
    try:
        relative = artifact_dir.resolve(strict=False).relative_to(
            projects_root.resolve(strict=False)
        )
    except ValueError:
        return "home", "ace-run"
    parts = relative.parts
    if len(parts) >= 4 and parts[1] == "artifacts":
        return parts[0], parts[2]
    return "home", "ace-run"
