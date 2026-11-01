"""Bounded exact-run observations for published-state repair and inventory."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.agents_sync.inventory_io import (
    is_imported as _is_imported,
    source_run_id as _source_run_id,
    text as _text,
    time_text as _time_text,
)
from sase.agents_sync.inventory_models import InventoryRun
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_io import MAX_JSON_BYTES
from sase.agents_sync.v2_models import V2RunRecord
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_run_state_wire import (
    AGENT_RUN_STATE_EVIDENCE_DISMISSED,
    AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
    AGENT_RUN_STATE_EVIDENCE_UNFINISHED,
    AGENT_RUN_STATE_OBSERVATION_MALFORMED,
    AGENT_RUN_STATE_OBSERVATION_MISSING,
    AGENT_RUN_STATE_OBSERVATION_PRESENT,
    AGENT_RUN_STATE_OBSERVATION_UNREADABLE,
    AGENT_RUN_STATE_REASON_CONFLICTING_TERMINAL,
    AGENT_RUN_STATE_REASON_IDENTITY_CONFLICT,
    AGENT_RUN_STATE_REASON_LIVE_EVIDENCE,
    AGENT_RUN_STATE_REASON_MALFORMED_EVIDENCE,
    AGENT_RUN_STATE_REASON_MISSING_EVIDENCE,
    AGENT_RUN_STATE_REASON_UNREADABLE_EVIDENCE,
    AgentRunIdentityWire,
    AgentRunStateIdentityClaimsWire,
    AgentRunStateObservationsResolveRequestWire,
    AgentRunStateObservationsResolveResponseWire,
    AgentRunStateRawObservationWire,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire

_READ_HOOK: Callable[[Path], None] | None = None


def _owner_token(owner: AgentOwnerIdentity) -> str:
    return f"{owner.username}@{owner.machine_name}"


def _read_bounded_json(path: Path) -> tuple[str, dict[str, Any] | None]:
    """Read one JSON object using existing byte bounds.

    Returns ``(read_status, payload)``. Oversized or permission failures are
    unreadable; decode failures are malformed. Missing files stay missing.
    """

    if _READ_HOOK is not None:
        _READ_HOOK(path)
    try:
        if not path.is_file():
            return AGENT_RUN_STATE_OBSERVATION_MISSING, None
        if path.stat().st_size > MAX_JSON_BYTES:
            return AGENT_RUN_STATE_OBSERVATION_UNREADABLE, None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AGENT_RUN_STATE_OBSERVATION_MISSING, None
    except (OSError, PermissionError):
        return AGENT_RUN_STATE_OBSERVATION_UNREADABLE, None
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return AGENT_RUN_STATE_OBSERVATION_MALFORMED, None
    if not isinstance(payload, dict):
        return AGENT_RUN_STATE_OBSERVATION_MALFORMED, None
    return AGENT_RUN_STATE_OBSERVATION_PRESENT, payload


def _claims_from_payloads(
    *payloads: dict[str, Any] | None,
    source_run_id: str | None = None,
) -> AgentRunStateIdentityClaimsWire | None:
    merged: dict[str, Any] = {}
    for payload in payloads:
        if payload:
            merged.update(payload)
    project = _text(merged.get("project")) or _text(merged.get("project_name"))
    owner = _text(merged.get("owner"))
    global_name = _text(merged.get("global_name"))
    local_name = _text(merged.get("local_name"))
    name = _text(merged.get("name"))
    claimed_run = _text(merged.get("source_run_id")) or source_run_id
    if not any((project, owner, global_name, local_name, name, claimed_run)):
        return None
    return AgentRunStateIdentityClaimsWire(
        project=project,
        owner=owner,
        global_name=global_name,
        local_name=local_name,
        name=name,
        source_run_id=claimed_run if claimed_run != source_run_id else None,
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
    meta: dict[str, Any] | None = None,
    source_run_id: str | None = None,
) -> AgentRunStateRawObservationWire:
    """Build a terminal-marker observation from a done.json read."""

    claims = _claims_from_payloads(meta, payload, source_run_id=source_run_id)
    if read_status != AGENT_RUN_STATE_OBSERVATION_PRESENT or payload is None:
        return AgentRunStateRawObservationWire(
            source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
            read_status=read_status,
            identity_claims=claims,
            imported=_is_imported(meta or {}, payload),
        )
    outcome = _text(payload.get("outcome"))
    started = _time_text((meta or {}).get("run_started_at")) or _time_text(
        payload.get("started_at")
    )
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
        imported=_is_imported(meta or {}, payload),
    )


def _unfinished_observation(
    *,
    meta: dict[str, Any] | None = None,
    source_run_id: str | None = None,
    read_status: str = AGENT_RUN_STATE_OBSERVATION_PRESENT,
) -> AgentRunStateRawObservationWire:
    """Build an unfinished observation from live metadata."""

    return AgentRunStateRawObservationWire(
        source=AGENT_RUN_STATE_EVIDENCE_UNFINISHED,
        read_status=read_status,
        identity_claims=_claims_from_payloads(meta, source_run_id=source_run_id),
        started_at=_time_text((meta or {}).get("run_started_at")),
        imported=_is_imported(meta or {}, None),
    )


def _observations_from_artifact_files(
    artifact: Path,
    *,
    source_run_id: str | None = None,
) -> tuple[AgentRunStateRawObservationWire, ...]:
    """Read current marker/metadata files for one artifact directory."""

    meta_status, meta = _read_bounded_json(artifact / "agent_meta.json")
    done_path = artifact / "done.json"
    done_status, done = _read_bounded_json(done_path)
    if done_status == AGENT_RUN_STATE_OBSERVATION_PRESENT and not done:
        done_status = AGENT_RUN_STATE_OBSERVATION_MALFORMED
    observations: list[AgentRunStateRawObservationWire] = []
    if done_status != AGENT_RUN_STATE_OBSERVATION_MISSING or done_path.is_file():
        observations.append(
            _observation_from_done_payload(
                done, done_status, meta=meta, source_run_id=source_run_id
            )
        )
    waiting_exists = (artifact / "waiting.json").is_file()
    pending_exists = (artifact / "pending_question.json").is_file()
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
                meta=meta, source_run_id=source_run_id, read_status=live_status
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


def _observations_from_dismissed_bundle(
    raw: dict[str, Any],
    *,
    source_run_id: str | None = None,
) -> AgentRunStateRawObservationWire:
    """Build a dismissed observation from one selected bundle payload."""

    return AgentRunStateRawObservationWire(
        source=AGENT_RUN_STATE_EVIDENCE_DISMISSED,
        read_status=AGENT_RUN_STATE_OBSERVATION_PRESENT,
        identity_claims=_claims_from_payloads(raw, source_run_id=source_run_id),
        state="dismissed",
        repeat_stopped=raw.get("repeat_stopped") is True,
        started_at=_time_text(raw.get("run_start_time") or raw.get("start_time")),
        finished_at=_time_text(raw.get("stop_time")),
        imported=_is_imported(raw, raw),
    )


def resolve_observations(
    *,
    project: str,
    owner: AgentOwnerIdentity,
    global_name: str,
    source_run_id: str,
    local_name: str | None,
    published_state: str,
    published_started_at: str | None,
    published_finished_at: str | None,
    observations: tuple[AgentRunStateRawObservationWire, ...],
) -> AgentRunStateObservationsResolveResponseWire:
    """Resolve published state against raw observations through Rust."""

    from sase.core.agent_run_state_facade import resolve_agent_run_state_observations

    return resolve_agent_run_state_observations(
        AgentRunStateObservationsResolveRequestWire(
            identity=AgentRunIdentityWire(
                project=project,
                owner=_owner_token(owner),
                global_name=global_name,
                source_run_id=source_run_id,
            ),
            local_name=local_name,
            published_state=published_state,
            published_started_at=published_started_at,
            published_finished_at=published_finished_at,
            observations=observations,
        )
    )


_UNRESOLVED_REASONS = frozenset(
    {
        AGENT_RUN_STATE_REASON_MISSING_EVIDENCE,
        AGENT_RUN_STATE_REASON_MALFORMED_EVIDENCE,
        AGENT_RUN_STATE_REASON_UNREADABLE_EVIDENCE,
        AGENT_RUN_STATE_REASON_IDENTITY_CONFLICT,
        AGENT_RUN_STATE_REASON_CONFLICTING_TERMINAL,
    }
)


def is_unresolved_reason(reason: str) -> bool:
    return reason in _UNRESOLVED_REASONS


def is_live_reason(reason: str) -> bool:
    return reason == AGENT_RUN_STATE_REASON_LIVE_EVIDENCE


def _artifact_source_run_id(
    target: ProjectTarget, record: AgentArtifactRecordWire
) -> str:
    durable = (
        record.agent_meta.artifact_agent_id if record.agent_meta is not None else None
    ) or record.timestamp
    return _source_run_id(target.project_key, record.workflow_dir_name, durable)


def _locate_artifact_dirs_for_run(
    target: ProjectTarget,
    local_name: str,
    source_run_id: str,
) -> tuple[tuple[Path, ...], str | None]:
    """Locate candidate artifact dirs via bounded index query.

    Missing or busy indexes are unresolved; this never falls back to an
    unbounded source walk.
    """

    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        query_agent_artifact_index_bounded,
    )
    from sase.core.agent_scan_wire import (
        AgentArtifactIndexQueryWire,
        AgentArtifactScanOptionsWire,
    )
    from sase.core.paths import sase_projects_dir

    index = default_agent_artifact_index_path()
    if not index.is_file():
        return (), None
    projects_root = sase_projects_dir()
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=True,
        active_limit=None,
        recent_completed_limit=None,
        include_hidden=True,
        freshness="cached",
        candidate_filter={
            "kind": "all",
            "filters": [
                {
                    "kind": "equals",
                    "field": "project",
                    "value": target.project_key,
                },
                {"kind": "equals", "field": "agent_name", "value": local_name},
            ],
        },
    )
    options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_workflow_dirs=("ace-run",),
        include_done_markers=True,
        include_workflow_state=False,
        include_waiting=True,
        only_projects=(target.project_key,),
        include_project_states=("all",),
    )
    try:
        snapshot = query_agent_artifact_index_bounded(
            index, projects_root, query, options
        )
    except (OSError, RuntimeError, ValueError, ImportError, AttributeError) as exc:
        return (), f"artifact index is not readable: {exc}"
    if snapshot is None:
        return (), "artifact index lock is busy"
    dirs: list[Path] = []
    seen: set[str] = set()
    for record in snapshot.records:
        if _artifact_source_run_id(target, record) != source_run_id:
            continue
        path = Path(record.artifact_dir)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        dirs.append(path)
    return tuple(dirs), None


def _locate_dismissed_bundles_for_run(
    target: ProjectTarget,
    source_run_id: str,
    local_name: str,
) -> tuple[tuple[Path, ...], str | None]:
    """Locate dismissed bundles for one selected run without a full archive scan."""

    from sase.core.dismissed_agents_facade import load_dismissed_bundle_summaries

    try:
        summaries = load_dismissed_bundle_summaries(
            project_name=target.project_key,
            cl_name=local_name,
            limit=None,
        )
    except (OSError, RuntimeError, ValueError, ImportError):
        return (), None
    matches: list[Path] = []
    for summary in summaries:
        summary_run_id = getattr(summary, "source_run_id", None)
        raw_suffix = getattr(summary, "raw_suffix", None)
        computed = None
        if isinstance(raw_suffix, str) and raw_suffix:
            computed = _source_run_id(target.project_key, "ace-run", raw_suffix)
        if (
            summary_run_id not in (None, "", source_run_id)
            and computed != source_run_id
        ):
            continue
        if summary_run_id != source_run_id and computed != source_run_id:
            continue
        path = Path(str(getattr(summary, "bundle_path", "")))
        if path.is_file():
            matches.append(path)
    return tuple(matches), None


def filesystem_observations_for_run(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    record: V2RunRecord,
) -> tuple[tuple[AgentRunStateRawObservationWire, ...], str | None]:
    """Load bounded marker/metadata observations for one published run."""

    del owner
    dirs, index_error = _locate_artifact_dirs_for_run(
        target, record.local_name, record.source_run_id
    )
    observations: list[AgentRunStateRawObservationWire] = []
    if index_error is not None:
        observations.append(
            AgentRunStateRawObservationWire(
                source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
                read_status=AGENT_RUN_STATE_OBSERVATION_UNREADABLE,
            )
        )
        return tuple(observations), index_error
    for artifact in dirs:
        observations.extend(
            _observations_from_artifact_files(
                artifact, source_run_id=record.source_run_id
            )
        )
    bundles, _bundle_error = _locate_dismissed_bundles_for_run(
        target, record.source_run_id, record.local_name
    )
    for bundle_path in bundles:
        status, payload = _read_bounded_json(bundle_path)
        if status != AGENT_RUN_STATE_OBSERVATION_PRESENT or payload is None:
            observations.append(
                AgentRunStateRawObservationWire(
                    source=AGENT_RUN_STATE_EVIDENCE_DISMISSED,
                    read_status=status,
                )
            )
            continue
        observations.append(
            _observations_from_dismissed_bundle(
                payload, source_run_id=record.source_run_id
            )
        )
    if not observations:
        observations.append(
            AgentRunStateRawObservationWire(
                source=AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
                read_status=AGENT_RUN_STATE_OBSERVATION_MISSING,
            )
        )
    return tuple(observations), None


def classify_artifact_state(
    record: AgentArtifactRecordWire,
    done: dict[str, Any] | None,
    *,
    identity: AgentIdentitySnapshot | None = None,
    local_name: str | None = None,
    global_name: str | None = None,
    source_run_id: str | None = None,
) -> str:
    """Classify live/done marker files through the observation resolver."""

    published = (
        "waiting"
        if record.waiting is not None or record.pending_question is not None
        else "active"
    )
    owner = (
        identity.owner
        if identity is not None and identity.owner is not None
        else AgentOwnerIdentity("owner", "machine")
    )
    observations: list[AgentRunStateRawObservationWire]
    if done is None:
        observations = [
            _unfinished_observation(
                source_run_id=source_run_id,
            )
        ]
    elif not done:
        observations = [
            _observation_from_done_payload(
                done,
                AGENT_RUN_STATE_OBSERVATION_MALFORMED,
                source_run_id=source_run_id,
            )
        ]
    else:
        observations = [
            _observation_from_done_payload(
                done,
                AGENT_RUN_STATE_OBSERVATION_PRESENT,
                source_run_id=source_run_id,
            )
        ]
    try:
        response = resolve_observations(
            project=record.project_name or "project",
            owner=owner,
            global_name=global_name or local_name or "agent",
            source_run_id=source_run_id or record.timestamp or "run",
            local_name=local_name,
            published_state=published,
            published_started_at=None,
            published_finished_at=None,
            observations=tuple(observations),
        )
    except (ValueError, RuntimeError):
        return published
    return response.selected_state
