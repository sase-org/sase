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
_ARTIFACT_CANDIDATE_LIMIT = 32
_DISMISSED_CANDIDATE_LIMIT = 64
_ACE_RUN_WORKFLOW = "ace-run"


def _owner_token(owner: AgentOwnerIdentity) -> str:
    return f"{owner.username}@{owner.machine_name}"


def _canonical_child(path: Path, root: Path) -> Path | None:
    """Return *path* when it resolves under *root*, including symlinked ancestors."""

    try:
        resolved = path.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    if not resolved.is_relative_to(root_resolved):
        return None
    return resolved


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


def _derived_run_id(
    project_key: str, durable: str, workflow: str = _ACE_RUN_WORKFLOW
) -> str:
    return _source_run_id(project_key, workflow, durable)


def _claims_from_marker_payload(
    payload: dict[str, Any] | None,
    *,
    project_key: str,
    workflow: str = _ACE_RUN_WORKFLOW,
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
        claimed_run = claimed_run or _derived_run_id(project_key, durable, workflow)
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
        claimed_run = claimed_run or _derived_run_id(project_key, durable)
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
    workflow: str = _ACE_RUN_WORKFLOW,
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
    workflow: str = _ACE_RUN_WORKFLOW,
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


def _observations_from_marker_payloads(
    *,
    meta_status: str,
    meta: dict[str, Any] | None,
    done_status: str,
    done: dict[str, Any] | None,
    waiting_exists: bool,
    pending_exists: bool,
    project_key: str,
    workflow: str = _ACE_RUN_WORKFLOW,
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


def _observations_from_artifact_files(
    artifact: Path,
    *,
    project_key: str,
    workflow: str = _ACE_RUN_WORKFLOW,
) -> tuple[AgentRunStateRawObservationWire, ...]:
    """Read current marker/metadata files for one artifact directory."""

    meta_status, meta = _read_bounded_json(artifact / "agent_meta.json")
    done_path = artifact / "done.json"
    done_status, done = _read_bounded_json(done_path)
    if done_status == AGENT_RUN_STATE_OBSERVATION_PRESENT and not done:
        done_status = AGENT_RUN_STATE_OBSERVATION_MALFORMED
    waiting_exists = (artifact / "waiting.json").is_file()
    pending_exists = (artifact / "pending_question.json").is_file()
    return _observations_from_marker_payloads(
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


def _index_lookup_overflow(snapshot: Any) -> bool:
    window = getattr(snapshot, "index_window", None)
    if window is not None and (
        getattr(window, "truncated", False) or getattr(window, "has_more", False)
    ):
        return True
    records = getattr(snapshot, "records", ())
    return len(records) > _ARTIFACT_CANDIDATE_LIMIT


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
        include_full_history=False,
        active_limit=_ARTIFACT_CANDIDATE_LIMIT + 1,
        recent_completed_limit=_ARTIFACT_CANDIDATE_LIMIT + 1,
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
        only_workflow_dirs=(_ACE_RUN_WORKFLOW,),
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
    if _index_lookup_overflow(snapshot):
        return (), "artifact index lookup is incomplete"
    dirs: list[Path] = []
    seen: set[str] = set()
    for record in snapshot.records:
        if _artifact_source_run_id(target, record) != source_run_id:
            continue
        path = Path(record.artifact_dir)
        canonical = _canonical_child(path, projects_root)
        if canonical is None:
            continue
        key = str(canonical)
        if key in seen:
            continue
        seen.add(key)
        dirs.append(canonical)
    return tuple(dirs), None


def _summary_is_candidate(
    summary: Any,
    target: ProjectTarget,
    source_run_id: str,
    local_name: str,
) -> bool:
    """Match an index row without treating ``agent_name`` as ``cl_name``."""

    project_name = getattr(summary, "project_name", None)
    if (
        isinstance(project_name, str)
        and project_name
        and project_name != target.project_key
    ):
        return False
    agent_name = getattr(summary, "agent_name", None)
    if isinstance(agent_name, str) and agent_name == local_name:
        return True
    summary_run_id = getattr(summary, "source_run_id", None)
    if summary_run_id == source_run_id:
        return True
    raw_suffix = getattr(summary, "raw_suffix", None)
    if isinstance(raw_suffix, str) and raw_suffix:
        return _derived_run_id(target.project_key, raw_suffix) == source_run_id
    return False


def _archive_bundle_is_current_for_run(
    payload: dict[str, Any],
    target: ProjectTarget,
    source_run_id: str,
    local_name: str,
) -> bool:
    """Accept a current bundle only when its archive identity matches the run."""

    agent_name = _text(payload.get("agent_name"))
    claimed_run = _text(payload.get("source_run_id"))
    raw_suffix = _text(payload.get("raw_suffix"))
    if raw_suffix:
        claimed_run = claimed_run or _derived_run_id(target.project_key, raw_suffix)
    if claimed_run is not None and claimed_run != source_run_id:
        return False
    if agent_name is not None and agent_name != local_name:
        return False
    return True


def _locate_dismissed_bundles_for_run(
    target: ProjectTarget,
    source_run_id: str,
    local_name: str,
) -> tuple[tuple[Path, ...], str | None]:
    """Locate dismissed bundles for one selected run without a rebuild."""

    from sase.ace.dismissed_bundle_index import query_summaries
    from sase.core.dismissed_agents_facade import dismissed_bundles_dir

    root = dismissed_bundles_dir()
    try:
        summaries = query_summaries(
            root,
            limit=_DISMISSED_CANDIDATE_LIMIT + 1,
        )
    except (OSError, RuntimeError, ValueError, ImportError):
        return (), None
    if summaries is None:
        return (), None
    if len(summaries) > _DISMISSED_CANDIDATE_LIMIT:
        return (), "dismissed index lookup is incomplete"
    matches: list[Path] = []
    seen: set[str] = set()
    for summary in summaries:
        if not _summary_is_candidate(summary, target, source_run_id, local_name):
            continue
        path = Path(str(getattr(summary, "bundle_path", "")))
        canonical = _canonical_child(path, root)
        if canonical is None or not canonical.is_file():
            continue
        key = str(canonical)
        if key in seen:
            continue
        seen.add(key)
        matches.append(canonical)
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
                artifact,
                project_key=target.project_key,
            )
        )
    bundles, bundle_error = _locate_dismissed_bundles_for_run(
        target, record.source_run_id, record.local_name
    )
    if bundle_error is not None and not observations:
        observations.append(
            AgentRunStateRawObservationWire(
                source=AGENT_RUN_STATE_EVIDENCE_DISMISSED,
                read_status=AGENT_RUN_STATE_OBSERVATION_UNREADABLE,
            )
        )
        return tuple(observations), bundle_error
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
        if not _archive_bundle_is_current_for_run(
            payload, target, record.source_run_id, record.local_name
        ):
            continue
        observations.append(
            _observations_from_dismissed_bundle(payload, project_key=target.project_key)
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
    meta: dict[str, Any] | None = None,
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
    project_key = record.project_name or "project"
    workflow = record.workflow_dir_name or _ACE_RUN_WORKFLOW
    if done is None:
        done_status = AGENT_RUN_STATE_OBSERVATION_MISSING
        done_payload = None
    elif not done:
        done_status = AGENT_RUN_STATE_OBSERVATION_MALFORMED
        done_payload = done
    else:
        done_status = AGENT_RUN_STATE_OBSERVATION_PRESENT
        done_payload = done
    meta_status = (
        AGENT_RUN_STATE_OBSERVATION_PRESENT
        if meta
        else AGENT_RUN_STATE_OBSERVATION_MISSING
    )
    observations = _observations_from_marker_payloads(
        meta_status=meta_status,
        meta=meta,
        done_status=done_status,
        done=done_payload,
        waiting_exists=record.waiting is not None,
        pending_exists=record.pending_question is not None,
        project_key=project_key,
        workflow=workflow,
        done_path_exists=done is not None,
    )
    try:
        response = resolve_observations(
            project=project_key,
            owner=owner,
            global_name=global_name or local_name or "agent",
            source_run_id=source_run_id or record.timestamp or "run",
            local_name=local_name,
            published_state=published,
            published_started_at=None,
            published_finished_at=None,
            observations=observations,
        )
    except (ValueError, RuntimeError):
        return published
    return response.selected_state
