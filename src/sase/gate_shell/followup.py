"""Launch the follow-up agent into a settled gate shell's lane."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sase.agent.launcher import spawn_agent_subprocess
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.gate_shell.followup_policy import GateFollowupPolicy
from sase.gate_shell.followup_prompt import (
    GateOptionOutcome,
    compose_gate_followup_prompt,
    format_gate_outcome_line,
)
from sase.gate_shell.log import GATE_SHELL_LOG_FILENAME, gate_shell_output_tail
from sase.gate_shell.models import GateShellState
from sase.notification_gates.branches import GateBranchData
from sase.shells.followup import (
    DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
    STARTER_SETTLE_POLL_SECONDS,
    FollowupLaunchResult,
    FollowupPersistence,
    ShellFollowupWorkspace,
    launch_shell_followup,
    record_followup_launched,
    record_followup_not_launchable,
    spawn_shell_family_successor,
    starter_identity,
    wait_for_starter,
)

_SAVED_FOLLOWUP_PROMPT_NAME = "gate_followup_prompt.md"

GATE_FOLLOWUP_PERSISTENCE = FollowupPersistence(
    agent_field="gate_followup_agent",
    error_field="gate_followup_error",
    prompt_path_field="gate_followup_prompt_path",
    degraded_reason_field="gate_followup_degraded_reason",
    prompt_filename=_SAVED_FOLLOWUP_PROMPT_NAME,
    prompt_label="Unlaunched gate follow-up prompt",
)


def launch_gate_followup_agent(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    project_name: str,
    gate_state: GateShellState,
    policy: GateFollowupPolicy,
    envelope: dict[str, Any],
    response: dict[str, Any],
    reason: str | None = None,
    settle_timeout_seconds: float = DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
) -> FollowupLaunchResult:
    """Launch the agent named by the resolved gate follow-up ``policy``.

    Returns the launch disposition. On failure, ``gate_followup_error`` is
    recorded on the gate shell member's own metadata; the caller is
    responsible for releasing the workspace claim and notifying.
    """
    lane = str(meta.get("agent_family") or "")
    if not lane:
        return FollowupLaunchResult(launched=False)

    parent_timestamp = meta.get("parent_timestamp")
    starter_role = starter_identity(project_name, parent_timestamp)[1]
    settled = wait_for_starter(
        project_name,
        parent_timestamp,
        timeout_seconds=settle_timeout_seconds,
        poll_seconds=STARTER_SETTLE_POLL_SECONDS,
    )
    fork_target = _fork_target(
        policy.fork,
        lane=lane,
        member_name=str(meta.get("name") or ""),
        settled=settled,
    )
    base_kwargs = _base_prompt_kwargs(
        artifacts_dir,
        meta,
        gate_state=gate_state,
        policy=policy,
        envelope=envelope,
        response=response,
        reason=reason,
    )

    def _compose(degraded_reason: str | None) -> str:
        return compose_gate_followup_prompt(
            fork_target=fork_target,
            workspace_degraded_reason=degraded_reason,
            **base_kwargs,
        )

    def _spawn(
        prompt: str, workspace_dir: str, workspace_num: int, transfer_pid: int | None
    ) -> Any:
        return spawn_shell_family_successor(
            family=lane,
            project_name=project_name,
            prompt=prompt,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            transfer_from_pid=transfer_pid,
            cl_name=_clean_str(meta.get("cl_name")),
            agent_family_role=starter_role,
            spawn_fn=spawn_agent_subprocess,
        )

    def _record_launched_result(
        agent_name: str | None, *, degraded_reason: str | None = None
    ) -> FollowupLaunchResult:
        return record_followup_launched(
            artifacts_dir,
            meta,
            agent_name=agent_name,
            degraded_reason=degraded_reason,
            persistence=GATE_FOLLOWUP_PERSISTENCE,
            update_meta_field=update_meta_field,
        )

    def _record_not_launchable_result(error: str, prompt: str) -> FollowupLaunchResult:
        return record_followup_not_launchable(
            artifacts_dir,
            meta,
            error=error,
            prompt=prompt,
            persistence=GATE_FOLLOWUP_PERSISTENCE,
            update_meta_field=update_meta_field,
        )

    workspace_policy = str(meta.get("gate_workspace_policy") or "inherit")
    transfer_from_pid = (
        None
        if workspace_policy == "release"
        else _optional_int(meta.get("gate_creator_claim_pid"))
    )

    return launch_shell_followup(
        project_name=project_name,
        meta_workspace_num=meta.get("workspace_num"),
        meta_workspace_dir=str(meta.get("workspace_dir") or ""),
        transfer_from_pid=transfer_from_pid,
        compose_prompt=_compose,
        spawn=_spawn,
        workspace=ShellFollowupWorkspace(
            meta_pairing_reason=_meta_pairing_degraded_reason,
            fresh_claim_reason=_fresh_claim_degraded_reason,
            workspace_zero_reason=_workspace_zero_degraded_reason,
        ),
        record_launched=_record_launched_result,
        record_not_launchable=_record_not_launchable_result,
    )


def build_suppressed_gate_followup_prompt(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    gate_state: GateShellState,
    policy: GateFollowupPolicy,
    envelope: dict[str, Any],
    response: dict[str, Any],
    reason: str | None,
) -> str:
    """Compose the follow-up prompt for a policy that will not be launched.

    Used when the agent that would otherwise be handed off is still live (the
    ``%auto`` short-circuit, or after a failed handoff): the prompt is
    stashed as an artifact instead of launched, so nothing the shell's author
    declared is silently lost. Never forks -- there is no settled starter to
    fork from, since the creator is still running this very call stack.
    """
    base_kwargs = _base_prompt_kwargs(
        artifacts_dir,
        meta,
        gate_state=gate_state,
        policy=policy,
        envelope=envelope,
        response=response,
        reason=reason,
    )
    return compose_gate_followup_prompt(
        fork_target=None, workspace_degraded_reason=None, **base_kwargs
    )


def _base_prompt_kwargs(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    gate_state: GateShellState,
    policy: GateFollowupPolicy,
    envelope: dict[str, Any],
    response: dict[str, Any],
    reason: str | None,
) -> dict[str, Any]:
    answered = gate_state in ("answered", "completed")
    options = _option_outcomes(envelope, response) if answered else ()
    outcome_line = format_gate_outcome_line(
        gate_state=gate_state,
        selected_labels=tuple(option.label for option in options),
        gate_timeout_seconds=float(envelope.get("gate_timeout_seconds") or 0.0),
        reason=reason,
    )
    gate_log_path = (
        str(Path(artifacts_dir) / GATE_SHELL_LOG_FILENAME)
        if "file" in policy.output
        else None
    )
    feedback = response.get("feedback")
    from sase.gate_shell.settlement import gate_decision_title

    return {
        "model": _clean_str(meta.get("model")),
        "reasoning_effort": _clean_str(meta.get("reasoning_effort")),
        "next_model": policy.model,
        "answered": answered,
        "title": gate_decision_title(envelope, meta),
        "gate_ref": f"{meta.get('gate_kind') or ''}/{meta.get('gate_id') or ''}",
        "outcome_line": outcome_line,
        "answered_via": (
            str(response["source"]) if answered and response.get("source") else None
        ),
        "opened_at": _format_unix(envelope.get("created_at_unix")),
        "answered_at": (
            _format_unix(response.get("responded_at_unix")) if answered else None
        ),
        "options": options,
        "reviewer_note": str(feedback) if feedback else None,
        "output": policy.output,
        "output_text": (
            gate_shell_output_tail(artifacts_dir) if "tail" in policy.output else ""
        ),
        "tail_lines": 200,
        "gate_log_path": gate_log_path,
        "next_action": policy.prompt,
    }


def _option_outcomes(
    envelope: dict[str, Any], response: dict[str, Any]
) -> tuple[GateOptionOutcome, ...]:
    try:
        branch_data = GateBranchData.from_envelope(envelope)
    except Exception:
        return ()
    options_by_id = {option.id: option for option in branch_data.options}
    results_by_id: dict[str, object] = {}
    raw_results = response.get("option_results")
    if isinstance(raw_results, list):
        for entry in raw_results:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                results_by_id[entry["id"]] = entry.get("result")
    raw_selected = response.get("selected_option_ids")
    selected_ids = (
        [str(option_id) for option_id in raw_selected]
        if isinstance(raw_selected, list)
        else []
    )
    outcomes = []
    for option_id in selected_ids:
        option = options_by_id.get(option_id)
        if option is None:
            continue
        outcomes.append(
            GateOptionOutcome(
                option_id=option_id,
                label=option.label,
                command=option.command.argv[0],
                result=results_by_id.get(option_id),
            )
        )
    return tuple(outcomes)


def _fork_target(
    fork: str, *, lane: str, member_name: str, settled: bool
) -> str | None:
    if not settled or fork == "none":
        return None
    if fork == "shell":
        return member_name or lane
    return lane


def _format_unix(value: object) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def _fresh_claim_degraded_reason(workspace_num: int, error: BaseException) -> str:
    return (
        f"The gate shell workspace claim transfer failed for workspace "
        f"#{workspace_num}: {error}. The follow-up was launched by taking a "
        "fresh claim on the same workspace, so the gate's approved-command "
        "workspace should still be present."
    )


def _workspace_zero_degraded_reason(
    workspace_num: int,
    error: BaseException,
    workspace_dir: str,
) -> str:
    return (
        f"The gate shell workspace claim transfer failed, and workspace "
        f"#{workspace_num} could not be freshly claimed because it is already "
        f"claimed: {error}. The follow-up was launched in workspace #0 "
        f"({workspace_dir}) instead. Do not assume the gate's approved-command "
        "workspace files are present; use the gate shell artifacts and log "
        "paths in this prompt."
    )


def _meta_pairing_degraded_reason(
    original_workspace_dir: str,
    primary_workspace_dir: str,
) -> str:
    return (
        "The gate shell member's own metadata did not record a claimed "
        f"workspace number for its directory ({original_workspace_dir or '<empty>'}), "
        "and that directory is not a checkout the workspace registry "
        f"recognizes, so it could not be repaired. The follow-up was launched "
        f"in workspace #0 ({primary_workspace_dir}) instead. Do not assume the "
        "gate's approved-command workspace files are present; use the gate "
        "shell artifacts and log paths in this prompt."
    )


def _clean_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "GATE_FOLLOWUP_PERSISTENCE",
    "build_suppressed_gate_followup_prompt",
    "launch_gate_followup_agent",
]
