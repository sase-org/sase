"""Marker-payload observations for published-state repair."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.agents_sync._publication_state_repair_observations_io import (
    ACE_RUN_WORKFLOW,
    derived_run_id,
    read_bounded_json,
)
from sase.agents_sync.inventory_io import (
    is_imported as _is_imported,
    text as _text,
    time_text as _time_text,
)
from sase.agents_sync.inventory_models import InventoryRun
from sase.core.agent_run_state_wire import (
    AGENT_RUN_STATE_EVIDENCE_DISMISSED,
    AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
    AGENT_RUN_STATE_EVIDENCE_UNFINISHED,
    AGENT_RUN_STATE_OBSERVATION_MALFORMED,
    AGENT_RUN_STATE_OBSERVATION_MISSING,
    AGENT_RUN_STATE_OBSERVATION_PRESENT,
    AGENT_RUN_STATE_OBSERVATION_UNREADABLE,
    AgentRunStateIdentityClaimsWire,
    AgentRunStateRawObservationWire,
)


def _claims_from_marker_payload(
    payload: dict[str, Any] | None,
    *,
    project_key: str,
    workflow: str = ACE_RUN_WORKFLOW,
) -> AgentRunStateIdentityClaimsWire | None:
    """Copy identity fields from one current marker/metadata object."""

    if not payload:
        return None
    project = _text(payload.get("project")) or _text(payload.get("project_name"))
    owner = _text(payload.get("owner"))
    global_name = _text(payload.get("global_name"))
    local_name = _text(payload.get("local_name"))
    name = _text(payload.get("name"))
    durable = _text(payload.get("artifact_agent_id"))
    claimed_run = _text(payload.get("source_run_id"))
    if durable:
        claimed_run = claimed_run or derived_run_id(project_key, durable, workflow)
    if not any((project, owner, global_name, local_name, name, claimed_run)):
        return None
    return AgentRunStateIdentityClaimsWire(
        project=project,
        owner=owner,
        global_name=global_name,
        local_name=local_name,
        name=name,
        source_run_id=claimed_run,
    )


def _claims_from_archive_payload(
    payload: dict[str, Any] | None,
    *,
    project_key: str,
) -> AgentRunStateIdentityClaimsWire | None:
    """Copy identity fields from a dismissed-bundle payload's archive keys."""

    if not payload:
        return None
    project = _text(payload.get("project_name")) or _text(payload.get("project"))
    username = _text(payload.get("source_username"))
    machine = _text(payload.get("source_machine"))
    owner = None
    if username and machine:
        owner = f"{username}@{machine}"
    elif _text(payload.get("owner")):
        owner = _text(payload.get("owner"))
    name = _text(payload.get("agent_name"))
    local_name = name or _text(payload.get("local_name"))
    global_name = _text(payload.get("global_name"))
    durable = _text(payload.get("raw_suffix"))
    claimed_run = _text(payload.get("source_run_id"))
    if durable:
        claimed_run = claimed_run or derived_run_id(project_key, durable)
    if not any((project, owner, global_name, local_name, name, claimed_run)):
        return None
    return AgentRunStateIdentityClaimsWire(
        project=project,
        owner=owner,
        global_name=global_name,
        local_name=local_name,
        name=name,
        source_run_id=claimed_run,
    )


def _session_child_state(payload: dict[str, Any], prefix: str) -> str | None:
    turn = payload.get("agent_session_turn")
    if isinstance(turn, dict):
        value = turn.get("state") or turn.get(f"{prefix}_state")
        if isinstance(value, str) and value:
            return value
    value = payload.get(f"{prefix}_state")
    return value if isinstance(value, str) and value else None


def _observation_from_done_payload(
    payload: dict[str, Any] | None,
    read_status: str,
    *,
    project_key: str,
    workflow: str = ACE_RUN_WORKFLOW,
    imported_meta: dict[str, Any] | None = None,
) -> AgentRunStateRawObservationWire:
    """Build a terminal-marker observation from a done.json read."""

    claims = _claims_from_marker_payload(
        payload, project_key=project_key, workflow=workflow
    )
    imported = _is_imported(imported_meta or {}, payload)
    if read_status != AGENT_RUN_STATE_OBSERVATION_PRESENT or payload is None:
        return AgentRunStateRawObservationWire(
            source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
            read_status=read_status,
            identity_claims=claims,
            imported=imported,
        )
    outcome = _text(payload.get("outcome"))
    started = _time_text(payload.get("started_at"))
    finished = _time_text(payload.get("finished_at"))
    return AgentRunStateRawObservationWire(
        source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
        read_status=read_status,
        identity_claims=claims,
        outcome=outcome,
        repeat_stopped=payload.get("repeat_stopped") is True,
        monitor_state=_session_child_state(payload, "monitor"),
        gate_state=_session_child_state(payload, "gate"),
        started_at=started,
        finished_at=finished,
        imported=imported,
    )


def _unfinished_observation(
    *,
    meta: dict[str, Any] | None = None,
    meta_status: str = AGENT_RUN_STATE_OBSERVATION_PRESENT,
    project_key: str,
    workflow: str = ACE_RUN_WORKFLOW,
) -> AgentRunStateRawObservationWire:
    """Build an unfinished observation from live metadata."""

    return AgentRunStateRawObservationWire(
        source=AGENT_RUN_STATE_EVIDENCE_UNFINISHED,
        read_status=meta_status,
        identity_claims=_claims_from_marker_payload(
            meta, project_key=project_key, workflow=workflow
        ),
        started_at=_time_text((meta or {}).get("run_started_at")),
        imported=_is_imported(meta or {}, None),
    )


def observations_from_marker_payloads(
    *,
    meta_status: str,
    meta: dict[str, Any] | None,
    done_status: str,
    done: dict[str, Any] | None,
    waiting_exists: bool,
    pending_exists: bool,
    project_key: str,
    workflow: str = ACE_RUN_WORKFLOW,
    done_path_exists: bool = False,
) -> tuple[AgentRunStateRawObservationWire, ...]:
    """Project current marker/metadata payloads into raw observations.

    Each current source keeps its own identity claims so contradictory
    names or durable IDs reach the Rust resolver instead of being merged.
    Malformed or unreadable metadata is emitted even when a terminal
    marker exists, so an anonymous marker cannot be accepted.
    """

    observations: list[AgentRunStateRawObservationWire] = []
    meta_unusable = meta_status in (
        AGENT_RUN_STATE_OBSERVATION_UNREADABLE,
        AGENT_RUN_STATE_OBSERVATION_MALFORMED,
    )
    if meta_unusable:
        observations.append(
            _unfinished_observation(
                meta=meta,
                meta_status=meta_status,
                project_key=project_key,
                workflow=workflow,
            )
        )
    if done_status != AGENT_RUN_STATE_OBSERVATION_MISSING or done_path_exists:
        observations.append(
            _observation_from_done_payload(
                done,
                done_status,
                project_key=project_key,
                workflow=workflow,
                imported_meta=meta,
            )
        )
    if done_status == AGENT_RUN_STATE_OBSERVATION_MISSING and (
        waiting_exists
        or pending_exists
        or meta_status == AGENT_RUN_STATE_OBSERVATION_PRESENT
    ):
        live_status = (
            meta_status
            if meta_status != AGENT_RUN_STATE_OBSERVATION_MISSING
            else AGENT_RUN_STATE_OBSERVATION_PRESENT
        )
        observations.append(
            _unfinished_observation(
                meta=meta,
                meta_status=live_status,
                project_key=project_key,
                workflow=workflow,
            )
        )
    elif (
        meta_status == AGENT_RUN_STATE_OBSERVATION_PRESENT
        and done_status != AGENT_RUN_STATE_OBSERVATION_MISSING
        and not meta_unusable
    ):
        # Current metadata identity stays visible beside the terminal marker
        # so a changed durable ID or name reaches Rust. Matching claims are
        # ignored once a terminal observation exists.
        observations.append(
            _unfinished_observation(
                meta=meta,
                meta_status=meta_status,
                project_key=project_key,
                workflow=workflow,
            )
        )
    if not observations:
        observations.append(
            AgentRunStateRawObservationWire(
                source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
                read_status=AGENT_RUN_STATE_OBSERVATION_MISSING,
            )
        )
    return tuple(observations)


def observations_from_artifact_files(
    artifact: Path,
    *,
    project_key: str,
    workflow: str = ACE_RUN_WORKFLOW,
) -> tuple[AgentRunStateRawObservationWire, ...]:
    """Read current marker/metadata files for one artifact directory."""

    meta_status, meta = read_bounded_json(artifact / "agent_meta.json")
    done_path = artifact / "done.json"
    done_status, done = read_bounded_json(done_path)
    if done_status == AGENT_RUN_STATE_OBSERVATION_PRESENT and not done:
        done_status = AGENT_RUN_STATE_OBSERVATION_MALFORMED
    waiting_exists = (artifact / "waiting.json").is_file()
    pending_exists = (artifact / "pending_question.json").is_file()
    return observations_from_marker_payloads(
        meta_status=meta_status,
        meta=meta,
        done_status=done_status,
        done=done,
        waiting_exists=waiting_exists,
        pending_exists=pending_exists,
        project_key=project_key,
        workflow=workflow,
        done_path_exists=done_path.is_file(),
    )


def observations_from_dismissed_bundle(
    raw: dict[str, Any],
    *,
    project_key: str,
) -> AgentRunStateRawObservationWire:
    """Build a dismissed observation from one selected bundle payload."""

    return AgentRunStateRawObservationWire(
        source=AGENT_RUN_STATE_EVIDENCE_DISMISSED,
        read_status=AGENT_RUN_STATE_OBSERVATION_PRESENT,
        identity_claims=_claims_from_archive_payload(raw, project_key=project_key),
        state="dismissed",
        repeat_stopped=raw.get("repeat_stopped") is True,
        started_at=_time_text(raw.get("run_start_time") or raw.get("start_time")),
        finished_at=_time_text(raw.get("stop_time")),
        imported=_is_imported(raw, raw),
    )


def observations_from_inventory_run(
    run: InventoryRun,
) -> tuple[AgentRunStateRawObservationWire, ...]:
    """Project an injected inventory run into raw observations."""

    label = str(run.source_label or "")
    if label.startswith(("primary commit history", "synthesized publication")):
        return (
            AgentRunStateRawObservationWire(
                source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
                read_status=AGENT_RUN_STATE_OBSERVATION_MISSING,
            ),
        )
    claims = AgentRunStateIdentityClaimsWire(
        global_name=run.global_name,
        local_name=run.local_name,
        source_run_id=run.source_run_id,
    )
    if run.state in ("completed", "failed", "stopped"):
        outcome = "completed" if run.state == "completed" else run.state
        return (
            AgentRunStateRawObservationWire(
                source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
                read_status=AGENT_RUN_STATE_OBSERVATION_PRESENT,
                identity_claims=claims,
                outcome=outcome,
                repeat_stopped=run.state == "stopped" and outcome == "completed",
                started_at=run.started_at,
                finished_at=run.finished_at,
            ),
        )
    if run.state == "dismissed":
        return (
            AgentRunStateRawObservationWire(
                source=AGENT_RUN_STATE_EVIDENCE_DISMISSED,
                read_status=AGENT_RUN_STATE_OBSERVATION_PRESENT,
                identity_claims=claims,
                state="dismissed",
                started_at=run.started_at,
                finished_at=run.finished_at,
            ),
        )
    if run.state in ("active", "waiting"):
        return (
            AgentRunStateRawObservationWire(
                source=AGENT_RUN_STATE_EVIDENCE_UNFINISHED,
                read_status=AGENT_RUN_STATE_OBSERVATION_PRESENT,
                identity_claims=claims,
                started_at=run.started_at,
            ),
        )
    return (
        AgentRunStateRawObservationWire(
            source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
            read_status=AGENT_RUN_STATE_OBSERVATION_MALFORMED,
            identity_claims=claims,
        ),
    )
