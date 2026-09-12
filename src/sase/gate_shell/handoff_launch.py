"""Execute a classified gate follow-up launch or recovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.gate_shell.followup import (
    GATE_FOLLOWUP_PERSISTENCE,
    build_suppressed_gate_followup_prompt,
    launch_gate_followup_agent,
)
from sase.gate_shell.followup_policy import GateFollowupPolicy
from sase.gate_shell.handoff import (
    apply_decision,
    classify_gate_handoff,
    collect_successor_evidence,
    merge_followup_fields,
    notify_handoff_failure,
    persist_attempt,
)
from sase.gate_shell.models import GateShellRecord, GateShellState
from sase.gate_shell.start_claim import release_gate_shell_claim
from sase.shells.followup import persist_followup_prompt
from sase.shells.settlement import (
    ShellSettlementConfig,
    settle_shell_claim_and_followup,
    stamp_shell_finished_at,
    touch_shell_refresh_pulse,
)


def record_selected_options(meta: dict[str, Any], response: Mapping[str, Any]) -> None:
    """Copy the stored answer's selected option ids onto gate metadata."""
    selected = response.get("selected_option_ids")
    if isinstance(selected, list) and selected:
        meta["gate_selected_option_ids"] = [str(item) for item in selected]


def launch_or_record_followup(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    gate_state: str,
    project_name: str | None,
    policy: GateFollowupPolicy | None,
    envelope: dict[str, Any],
    response: dict[str, Any],
    reason: str | None,
    already_settled: bool,
    resume: bool,
    config: ShellSettlementConfig,
    done_marker: Mapping[str, Any] | None = None,
) -> None:
    """Launch, adopt, wait, or record a follow-up according to the core decision."""
    followup_requested = bool(policy is not None and meta.get("gate_next_action"))
    evidence = collect_successor_evidence(
        project_name=project_name,
        family=str(meta.get("agent_family") or ""),
        expected_suffix=(policy.suffix if policy is not None else None),
        recorded_agent=str(meta.get("gate_followup_agent") or "") or None,
    )
    decision = classify_gate_handoff(
        meta,
        mode="resume" if resume else ("diagnose" if already_settled else "settle"),
        already_settled=already_settled,
        followup_requested=followup_requested,
        successor_evidence=evidence,
    )
    apply_decision(artifacts_dir, meta, decision)
    if decision.get("recovery") == "adopt":
        persist_attempt(
            artifacts_dir,
            meta,
            stage="launched",
            live=False,
            fingerprint=str(meta.get("gate_request_fingerprint") or ""),
        )
        return
    if not decision.get("launch_allowed"):
        if not already_settled and decision.get("recovery") != "wait":
            _release_failed_attempt_claim(meta, project_name, artifacts_dir)
        return
    fingerprint = str(meta.get("gate_request_fingerprint") or "")
    persist_attempt(
        artifacts_dir,
        meta,
        stage="preparing",
        live=True,
        fingerprint=fingerprint,
    )
    try:
        persist_attempt(
            artifacts_dir,
            meta,
            stage="launching",
            live=True,
            fingerprint=fingerprint,
        )
        settle_error = settle_shell_claim_and_followup(
            artifacts_dir,
            meta,
            shell_state=gate_state,
            project_name=project_name,
            config=config,
            release_claim=lambda release_meta, release_project_name: (
                release_gate_shell_claim(
                    release_meta,
                    release_project_name,
                    artifacts_dir=artifacts_dir,
                )
            ),
            launch_followup=launch_gate_followup_agent,
            launch_kwargs={
                "project_name": project_name,
                "gate_state": gate_state,
                "policy": policy,
                "envelope": envelope,
                "response": response,
                "reason": reason,
            },
            update_meta_field=update_meta_field,
        )
    except Exception as exc:
        persist_attempt(
            artifacts_dir,
            meta,
            stage="failed",
            live=False,
            fingerprint=fingerprint,
            error=exc,
            error_stage="launching",
        )
        _release_failed_attempt_claim(meta, project_name, artifacts_dir)
        notify_handoff_failure(meta, error=exc, stage="launching")
        return
    disk = _read_meta(artifacts_dir)
    merge_followup_fields(meta, disk)
    if settle_error:
        meta["gate_followup_error"] = settle_error
        persist_attempt(
            artifacts_dir,
            meta,
            stage="failed",
            live=False,
            fingerprint=fingerprint,
            error=RuntimeError(settle_error),
            error_stage="launching",
        )
        notify_handoff_failure(meta, error=settle_error, stage="launching")
        return
    persist_attempt(
        artifacts_dir,
        meta,
        stage="launched",
        live=False,
        fingerprint=fingerprint,
    )
    _ = done_marker


def settle_already_terminal_handoff(
    record: GateShellRecord,
    meta: dict[str, Any],
    *,
    envelope: dict[str, Any],
    response: dict[str, Any],
    policy: GateFollowupPolicy | None,
    reason: str | None,
    resume: bool,
    config: ShellSettlementConfig,
    done_marker: dict[str, Any],
) -> GateShellRecord:
    """Recover or diagnose a gate that is already terminal on disk."""
    artifacts_dir = record.artifacts_dir
    project_name = record.project_name
    launch_or_record_followup(
        artifacts_dir,
        meta,
        gate_state=str(meta.get("gate_state") or record.gate_state),
        project_name=project_name,
        policy=policy,
        envelope=envelope,
        response=response,
        reason=reason,
        already_settled=True,
        resume=resume,
        config=config,
    )
    disk = _read_meta(artifacts_dir)
    merge_followup_fields(meta, disk)
    _write_meta(artifacts_dir, meta)
    followup_fields: dict[str, Any] = {
        key: meta[key]
        for key in (
            "gate_followup_agent",
            "gate_followup_outcome",
            "gate_followup_error",
            "gate_followup_attempt_id",
        )
        if key in meta
    }
    marker: dict[str, Any] = {**done_marker, **followup_fields}
    stamp_shell_finished_at(marker)
    write_done_marker_and_update_index(artifacts_dir, marker)
    touch_shell_refresh_pulse(project_name)
    from sase.gate_shell.store import read_gate_shell_marker

    return read_gate_shell_marker(project_name, artifacts_dir) or record


def suppress_live_creator_followup(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    policy: GateFollowupPolicy | None,
    gate_state: GateShellState,
    envelope: dict[str, Any],
    response: dict[str, Any],
    reason: str | None,
) -> None:
    """Stash or skip follow-up when the creator process is still live."""
    if policy is None:
        return
    if meta.get("gate_kind") in {"plan", "epic_plan"}:
        meta["gate_followup_outcome"] = "suppressed"
        return
    prompt = build_suppressed_gate_followup_prompt(
        artifacts_dir,
        meta,
        gate_state=gate_state,
        policy=policy,
        envelope=envelope,
        response=response,
        reason=reason,
    )
    prompt_path = persist_followup_prompt(
        artifacts_dir, prompt, GATE_FOLLOWUP_PERSISTENCE
    )
    meta["gate_followup_outcome"] = "suppressed"
    if prompt_path:
        meta["gate_followup_prompt_path"] = prompt_path


def _release_failed_attempt_claim(
    meta: dict[str, Any],
    project_name: str | None,
    artifacts_dir: str,
) -> None:
    """Release a failed attempt's workspace claim unless a successor owns it."""
    if meta.get("gate_followup_agent"):
        return
    try:
        release_error = release_gate_shell_claim(
            meta, project_name, artifacts_dir=artifacts_dir
        )
    except Exception as cleanup_error:
        existing = str(meta.get("gate_followup_error") or "")
        meta["gate_followup_error"] = (
            f"{existing}; cleanup: {cleanup_error}" if existing else str(cleanup_error)
        )
        return
    if release_error:
        existing = str(meta.get("gate_followup_error") or "")
        meta["gate_followup_error"] = (
            f"{existing}; cleanup: {release_error}" if existing else release_error
        )


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    with meta_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"agent_meta.json at {artifacts_dir!r} is not an object")
    data["artifacts_dir"] = artifacts_dir
    return data


def _write_meta(artifacts_dir: str, meta: dict[str, Any]) -> None:
    payload = dict(meta)
    payload.pop("artifacts_dir", None)
    write_agent_meta_atomic(
        artifacts_dir,
        payload,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )


__all__ = [
    "launch_or_record_followup",
    "record_selected_options",
    "settle_already_terminal_handoff",
    "suppress_live_creator_followup",
]
