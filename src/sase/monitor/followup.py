"""Launch the follow-up agent into a monitor's lane once it goes terminal.

Reuses the same ``%id(<suffix>, family=<parent>)`` family-attach machinery a
user-typed directive would trigger (:mod:`sase.agent.family_attach`): the
monitor's lane is resolved to a family-attach plan, encoded into the child's
launch environment, and the child's own runner boot adopts the resulting name,
family, and role when it starts -- exactly as it would for an interactive
``%id(@, family=acme)`` launch.
"""

from __future__ import annotations

import os
from typing import Any

from sase.agent.launcher import spawn_agent_subprocess
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.shells.followup import (
    DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
    STARTER_SETTLE_POLL_SECONDS as _STARTER_SETTLE_POLL_SECONDS,
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

from .followup_prompt import DEFAULT_NEXT_OUTPUT, compose_followup_prompt
from .logs import monitor_log_path
from .output import OutputCapture

_SAVED_FOLLOWUP_PROMPT_NAME = "monitor_followup_prompt.md"

_FOLLOWUP_PERSISTENCE = FollowupPersistence(
    agent_field="monitor_followup_agent",
    error_field="monitor_followup_error",
    prompt_path_field="monitor_followup_prompt_path",
    degraded_reason_field="monitor_followup_degraded_reason",
    prompt_filename=_SAVED_FOLLOWUP_PROMPT_NAME,
    prompt_label="Unlaunched monitor follow-up prompt",
)


def launch_followup_agent(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    project_name: str,
    timeout_kind: str | None = None,
    settle_timeout_seconds: float = DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
    transfer_from_pid: int | None = None,
) -> FollowupLaunchResult:
    """Launch the agent named by ``monitor_next_action`` into the same lane.

    Returns the launch disposition. On failure, ``monitor_followup_error`` is
    recorded on the monitor member's own metadata; the caller is responsible
    for releasing the workspace claim and notifying.
    """
    next_action = str(meta.get("monitor_next_action") or "")
    lane = str(meta.get("agent_family") or "")
    if not next_action or not lane:
        return FollowupLaunchResult(launched=False)

    parent_timestamp = meta.get("parent_timestamp")
    starter_name, starter_role = _starter_identity(project_name, parent_timestamp)
    settled = _wait_for_starter(
        project_name,
        parent_timestamp,
        timeout_seconds=settle_timeout_seconds,
    )

    prompt_kwargs: dict[str, Any] = {
        "starter_name": starter_name if settled else None,
        "family_name": lane,
        "command": str(meta.get("monitor_command") or ""),
        "cwd": str(meta.get("monitor_cwd") or ""),
        "reason": str(meta.get("monitor_reason") or ""),
        "monitor_state": monitor_state,
        "exit_code": exit_code,
        "started_at": meta.get("run_started_at"),
        "stopped_at": meta.get("stopped_at"),
        "elapsed_seconds": elapsed_seconds,
        "timeout_seconds": float(meta.get("monitor_timeout_seconds") or 0.0),
        "idle_timeout_seconds": float(meta.get("monitor_idle_timeout_seconds") or 0.0),
        "timeout_kind": timeout_kind or meta.get("monitor_timeout_kind"),
        "monitor_id": str(meta.get("monitor_id") or ""),
        "output_text": capture.retained_text(),
        "tail_lines": int(meta.get("monitor_tail_lines") or 200),
        "total_bytes": capture.total_bytes,
        "output_truncated": capture.truncated,
        "next_action": next_action,
        "next_output": str(meta.get("monitor_next_output") or DEFAULT_NEXT_OUTPUT),
        "output_log_path": str(monitor_log_path(artifacts_dir)),
        "model": _clean_str(meta.get("model")),
        "reasoning_effort": _clean_str(meta.get("reasoning_effort")),
        "next_model": _clean_str(meta.get("monitor_next_model")),
    }

    def _compose(degraded_reason: str | None) -> str:
        return compose_followup_prompt(
            **prompt_kwargs, workspace_degraded_reason=degraded_reason
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
        return _record_launched(
            artifacts_dir, meta, agent_name, degraded_reason=degraded_reason
        )

    def _record_not_launchable_result(error: str, prompt: str) -> FollowupLaunchResult:
        return _record_not_launchable(artifacts_dir, meta, error, prompt)

    transfer_pid = os.getpid() if transfer_from_pid is None else transfer_from_pid
    return launch_shell_followup(
        project_name=project_name,
        meta_workspace_num=meta.get("workspace_num"),
        meta_workspace_dir=str(meta.get("workspace_dir") or ""),
        transfer_from_pid=transfer_pid,
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


def _record_launched(
    artifacts_dir: str,
    meta: dict[str, Any],
    agent_name: str | None,
    *,
    degraded_reason: str | None = None,
) -> FollowupLaunchResult:
    return record_followup_launched(
        artifacts_dir,
        meta,
        agent_name=agent_name,
        degraded_reason=degraded_reason,
        persistence=_FOLLOWUP_PERSISTENCE,
        update_meta_field=update_meta_field,
    )


def _record_not_launchable(
    artifacts_dir: str,
    meta: dict[str, Any],
    error: str,
    prompt: str,
) -> FollowupLaunchResult:
    return record_followup_not_launchable(
        artifacts_dir,
        meta,
        error=error,
        prompt=prompt,
        persistence=_FOLLOWUP_PERSISTENCE,
        update_meta_field=update_meta_field,
    )


def _fresh_claim_degraded_reason(
    workspace_num: int,
    error: BaseException,
) -> str:
    return (
        f"The monitor workspace claim transfer failed for workspace #{workspace_num}: "
        f"{error}. The follow-up was launched by taking a fresh claim on the same "
        "workspace, so the monitored command's workspace should still be present."
    )


def _workspace_zero_degraded_reason(
    workspace_num: int,
    error: BaseException,
    workspace_dir: str,
) -> str:
    return (
        f"The monitor workspace claim transfer failed, and workspace #{workspace_num} "
        f"could not be freshly claimed because it is already claimed: {error}. "
        f"The follow-up was launched in workspace #0 ({workspace_dir}) instead. Do not "
        "assume the monitored command's workspace files are present; use the monitor "
        "artifacts and log paths in this prompt."
    )


def _meta_pairing_degraded_reason(
    original_workspace_dir: str,
    primary_workspace_dir: str,
) -> str:
    return (
        "The monitor member's own metadata did not record a claimed workspace "
        f"number for its directory ({original_workspace_dir or '<empty>'}), and that "
        "directory is not a checkout the workspace registry recognizes, so it could "
        f"not be repaired. The follow-up was launched in workspace #0 "
        f"({primary_workspace_dir}) instead. Do not assume the monitored command's "
        "workspace files are present; use the monitor artifacts and log paths in "
        "this prompt."
    )


def _clean_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _starter_identity(
    project_name: str, parent_timestamp: object
) -> tuple[str | None, str | None]:
    return starter_identity(project_name, parent_timestamp)


def _wait_for_starter(
    project_name: str,
    parent_timestamp: object,
    *,
    timeout_seconds: float,
) -> bool:
    """Poll (bounded) for the starter's terminal marker before forking its chat.

    Two agents must never be live in one lane at once, and ``#fork`` needs
    the starter's chat to already be saved. Returns ``False`` -- continue
    without the ``#fork`` prefix -- rather than dropping the follow-up.
    """
    return wait_for_starter(
        project_name,
        parent_timestamp,
        timeout_seconds=timeout_seconds,
        poll_seconds=_STARTER_SETTLE_POLL_SECONDS,
    )


__all__ = [
    "DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS",
    "FollowupLaunchResult",
    "launch_followup_agent",
]
