"""Gate-shell claim, follow-up, and terminal marker settlement."""

from __future__ import annotations

import json
import os
import time
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
from sase.gate_shell.followup_policy import (
    GateFollowupPolicy,
    resolve_gate_branch_presentation,
    resolve_gate_followup,
)
from sase.gate_shell.log import gate_shell_output_tail
from sase.gate_shell.models import GateShellRecord, GateShellState
from sase.gate_shell.start_claim import release_gate_shell_claim
from sase.history.chat import save_chat_history
from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.paths import CANCELLATION_FILENAME, RESPONSE_FILENAME
from sase.shells.followup import persist_followup_prompt
from sase.shells.settlement import (
    ShellSettlementConfig,
    finalize_shell_workflow_state,
    project_name_from_artifacts_dir as shell_project_name_from_artifacts_dir,
    settle_shell_claim_and_followup,
    touch_shell_refresh_pulse,
)

GATE_FOLLOWUP_DEGRADED_OUTCOME = "launched-degraded"
LOST_FOLLOWUP_ERROR = "follow-up not launched because the gate shell was marked lost"

_GATE_SETTLEMENT_CONFIG = ShellSettlementConfig(
    next_action_field="gate_next_action",
    agent_field="gate_followup_agent",
    outcome_field="gate_followup_outcome",
    error_field="gate_followup_error",
    degraded_reason_field="gate_followup_degraded_reason",
    prompt_path_field="gate_followup_prompt_path",
    lost_state="lost",
    stopped_state="stopped",
    lost_followup_error=LOST_FOLLOWUP_ERROR,
    degraded_outcome=GATE_FOLLOWUP_DEGRADED_OUTCOME,
    fallback_followup_error="gate follow-up launch failed",
    missing_project_error=(
        "could not resolve the gate shell's project from its artifacts path"
    ),
)


def settle_gate_shell(
    record: GateShellRecord,
    *,
    gate_state: GateShellState,
    reason: str | None = None,
    creator_live: bool = False,
) -> GateShellRecord:
    """Settle a gate-shell member into ``gate_state``.

    Never launches a follow-up, releases a claim, or notifies until the shell
    itself is terminal and its artifact index is visible -- otherwise a
    forked successor could resolve ``#fork`` before this shell's own
    decision record and chat exist.

    ``creator_live=True`` marks a settlement that runs inside the still-live
    creator's own process (the ``%auto`` short-circuit, or after a failed
    handoff): no follow-up is launched and no claim is disposed of, because
    the creator itself still owns the lane and the workspace. A policy that
    would otherwise have launched is stashed as an artifact instead, so
    nothing the shell's author declared is silently lost.
    """
    artifacts_dir = record.artifacts_dir
    meta = _read_meta(artifacts_dir)
    if _is_terminal_meta(meta):
        return record

    envelope, response, cancellation = _bundle_documents(meta)
    policy = resolve_gate_followup(envelope, gate_state=gate_state, response=response)
    _apply_branch_policy(
        meta, policy=policy, gate_state=gate_state, envelope=envelope, response=response
    )
    meta["gate_state"] = "settling"
    _write_meta(artifacts_dir, meta)

    decision_path, decision_text = _write_decision_record(
        artifacts_dir,
        meta,
        gate_state=gate_state,
        reason=reason,
        envelope=envelope,
        response=response,
        cancellation=cancellation,
    )
    meta["gate_decision_path"] = str(decision_path)
    meta["chat_path"] = _write_settlement_chat(artifacts_dir, meta, decision_text)
    _write_meta(artifacts_dir, meta)

    done_marker = _done_marker(meta, gate_state=gate_state, reason=reason)
    write_done_marker_and_update_index(artifacts_dir, done_marker)
    finalize_shell_workflow_state(artifacts_dir)

    meta = _read_meta(artifacts_dir)
    meta["gate_state"] = gate_state
    meta["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_meta(artifacts_dir, meta)

    project_name = project_name_from_artifacts_dir(artifacts_dir)
    if creator_live:
        _suppress_live_creator_followup(
            artifacts_dir,
            meta,
            policy=policy,
            gate_state=gate_state,
            envelope=envelope,
            response=response,
            reason=reason,
        )
    else:
        settle_error = settle_shell_claim_and_followup(
            artifacts_dir,
            meta,
            shell_state=gate_state,
            project_name=project_name,
            config=_GATE_SETTLEMENT_CONFIG,
            release_claim=release_gate_shell_claim,
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
        if settle_error:
            meta["gate_followup_error"] = settle_error
    _write_meta(artifacts_dir, meta)

    done_marker = _done_marker(meta, gate_state=gate_state, reason=reason)
    write_done_marker_and_update_index(artifacts_dir, done_marker)
    touch_shell_refresh_pulse(project_name)

    from sase.gate_shell.store import read_gate_shell_marker

    return (
        read_gate_shell_marker(project_name or record.project_name, artifacts_dir)
        or record
    )


def _suppress_live_creator_followup(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    policy: GateFollowupPolicy | None,
    gate_state: GateShellState,
    envelope: dict[str, Any],
    response: dict[str, Any],
    reason: str | None,
) -> None:
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


def _done_marker(
    meta: dict[str, Any],
    *,
    gate_state: GateShellState,
    reason: str | None,
) -> dict[str, Any]:
    marker: dict[str, Any] = {
        "outcome": "gated",
        "gate_state": gate_state,
        "status_label": meta.get("gate_stop_status"),
        "finished_at": time.time(),
    }
    for key in (
        "name",
        "workspace_num",
        "workspace_dir",
        "pid",
        "model",
        "llm_provider",
        "vcs_provider",
        "gate_id",
        "gate_kind",
        "gate_bundle_path",
        "gate_notification_id",
        "gate_followup_agent",
        "gate_followup_outcome",
        "gate_followup_error",
        "gate_followup_degraded_reason",
        "gate_followup_prompt_path",
        "gate_decision_path",
        "chat_path",
    ):
        if key in meta:
            marker[key] = meta[key]
    if reason:
        marker["reason"] = reason
    project_name = project_name_from_artifacts_dir(str(meta.get("artifacts_dir", "")))
    if project_name:
        from sase.workflows.utils import get_project_file_path

        marker["project_file"] = get_project_file_path(project_name)
    return marker


def _write_decision_record(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    gate_state: GateShellState,
    reason: str | None,
    envelope: dict[str, Any],
    response: dict[str, Any],
    cancellation: dict[str, Any],
) -> tuple[Path, str]:
    path = Path(artifacts_dir) / "gate_decision.md"
    title = gate_decision_title(envelope, meta)
    selected = response.get("selected_option_ids")
    selected_ids = (
        [str(item) for item in selected] if isinstance(selected, list) else []
    )
    lines = [
        f"# {title}",
        "",
        f"Gate state: {gate_state}",
    ]
    if reason:
        lines.append(f"Reason: {reason}")
    if selected_ids:
        lines.append("Selected options: " + ", ".join(selected_ids))
    branch_lines = _branch_lines(envelope, selected_ids)
    if branch_lines:
        lines.extend(["", "Branches:", ""])
        lines.extend(branch_lines)
    if response.get("feedback"):
        lines.extend(["", "Reviewer note:", "", str(response["feedback"])])
    if cancellation:
        lines.extend(["", "Cancellation:", "", json.dumps(cancellation, indent=2)])
    option_results = response.get("option_results")
    if isinstance(option_results, list) and option_results:
        lines.extend(["", "Option results:", ""])
        lines.append(json.dumps(option_results, indent=2, sort_keys=True))
    tail = gate_shell_output_tail(artifacts_dir)
    if tail:
        lines.extend(["", "Output tail:", "", "```text", tail.rstrip("\n"), "```"])
    text = "\n".join(lines).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    return path, text


def _branch_lines(envelope: dict[str, Any], selected_ids: list[str]) -> list[str]:
    """Render every branch, marking the one the reviewer selected."""
    try:
        branch_data = GateBranchData.from_envelope(envelope)
    except Exception:
        return []
    selected_set = set(selected_ids)
    labels = {option.id: option.label for option in branch_data.options}
    lines = []
    for branch in branch_data.branches:
        marker = "x" if selected_set and selected_set == set(branch) else " "
        label = " + ".join(labels.get(option_id, option_id) for option_id in branch)
        lines.append(f"- [{marker}] {label} ({'+'.join(branch)})")
    return lines


def _write_settlement_chat(
    artifacts_dir: str,
    meta: dict[str, Any],
    decision_text: str,
) -> str:
    """Save the settle-time chat file that ``#fork`` reads as this shell's turn."""
    member_name = str(meta.get("name") or "")
    timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    prompt = (
        f"sase gate answer --id {meta.get('gate_id')} --kind {meta.get('gate_kind')}"
    )
    return save_chat_history(
        prompt,
        decision_text,
        "ace-run",
        agent=member_name,
        timestamp=timestamp,
        branch_or_workspace=meta.get("cl_name"),
        metadata_agent=member_name,
        metadata_model=meta.get("model"),
        metadata_llm_provider=meta.get("llm_provider"),
    )


def _apply_branch_policy(
    meta: dict[str, Any],
    *,
    policy: GateFollowupPolicy | None,
    gate_state: GateShellState,
    envelope: dict[str, Any],
    response: dict[str, Any],
) -> None:
    """Write the resolved branch presentation and follow-up policy onto ``meta``.

    ``gate_next_action`` is the field ``settle_shell_claim_and_followup`` keys
    launch decisions off of, so a policy that resolves to ``None`` -- an
    unmapped reserved branch, or explicit ``prompt: null`` -- must delete it
    rather than leave a stale value seeded at creation time from the
    top-level ``shell.next``.
    """
    status, accent = resolve_gate_branch_presentation(
        envelope, gate_state=gate_state, response=response
    )
    if status is not None:
        meta["gate_stop_status"] = status
    if accent is not None:
        meta["gate_accent"] = accent
    if policy is None:
        meta.pop("gate_next_action", None)
        return
    meta["gate_next_action"] = policy.prompt
    meta["gate_next_fork"] = policy.fork
    meta["gate_next_output"] = ",".join(policy.output)
    meta["gate_next_raw_prompt"] = policy.raw_prompt
    if policy.model:
        meta["gate_next_model"] = policy.model
    else:
        meta.pop("gate_next_model", None)
    if policy.suffix:
        meta["gate_next_suffix"] = policy.suffix
    else:
        meta.pop("gate_next_suffix", None)
    if policy.role:
        meta["gate_next_role"] = policy.role
    else:
        meta.pop("gate_next_role", None)


def _bundle_documents(
    meta: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return this shell's ``(envelope, response, cancellation)`` documents."""
    bundle = _bundle_path(meta)
    if bundle is None:
        return {}, {}, {}
    return (
        _read_json(bundle / "request.json"),
        _read_json(bundle / RESPONSE_FILENAME),
        _read_json(bundle / CANCELLATION_FILENAME),
    )


def project_name_from_artifacts_dir(artifacts_dir: str) -> str | None:
    """Return the project containing a gate-shell artifacts directory."""
    return shell_project_name_from_artifacts_dir(artifacts_dir)


def gate_decision_title(envelope: dict[str, Any], meta: dict[str, Any]) -> str:
    """Return the human-facing title for a gate's decision record and prompt."""
    presentation = envelope.get("presentation")
    if isinstance(presentation, dict) and presentation.get("title"):
        return str(presentation["title"])
    return str(meta.get("gate_label") or meta.get("gate_id") or "Gate decision")


def _bundle_path(meta: dict[str, Any]) -> Path | None:
    value = meta.get("gate_bundle_path")
    return Path(value) if isinstance(value, str) and value else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path)
    except Exception:
        return {}


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    with meta_path.open(encoding="utf-8") as f:
        data = json.load(f)
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


def _is_terminal_meta(meta: dict[str, Any]) -> bool:
    return meta.get("gate_state") in {
        "answered",
        "completed",
        "failed",
        "timeout",
        "stopped",
        "lost",
    }


__all__ = [
    "GATE_FOLLOWUP_DEGRADED_OUTCOME",
    "LOST_FOLLOWUP_ERROR",
    "gate_decision_title",
    "project_name_from_artifacts_dir",
    "settle_gate_shell",
]
