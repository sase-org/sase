"""Launch the follow-up agent into a monitor's lane once it goes terminal.

Reuses the same ``%id(<suffix>, family=<parent>)`` family-attach machinery a
user-typed directive would trigger (:mod:`sase.agent.family_attach`): the
monitor's lane is resolved to a family-attach plan, encoded into the child's
launch environment, and the child's own runner boot adopts the resulting name,
family, and role when it starts -- exactly as it would for an interactive
``%id(@, family=acme)`` launch.
"""

from __future__ import annotations

from dataclasses import replace
import os
from typing import Any

from sase.agent._family_attach_resolution import resolve_family_attach_plan
from sase.agent._family_attach_types import FamilyAttachDirective, FamilyAttachError
from sase.agent.detached_child import spawn_family_successor
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
    starter_identity,
    vcs_ref_from_meta,
    wait_for_starter,
)

from .continuation_delivery import (
    claim_ordinary_continuation_dispatch,
    continuation_delivery_env,
    launch_wire_extra,
    mark_ordinary_continuation_terminal,
    maybe_crash,
    queue_launch_prefix,
)
from .delivery import update_delivery_workspace

from .followup_prompt import compose_followup_prompt
from .diagnostics import (
    diagnostic_manifest,
    read_selected_diagnostics_text,
    retained_log_metadata,
)
from .logs import monitor_log_path
from .output import OutputCapture
from .result_projection import (
    LEGACY_NEXT_OUTPUT,
    build_monitor_result_wire,
    select_monitor_result_evidence,
)

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

    manifest = diagnostic_manifest(artifacts_dir)
    retained_log = retained_log_metadata(artifacts_dir)
    next_output = str(meta.get("monitor_next_output") or LEGACY_NEXT_OUTPUT)
    monitor_result = build_monitor_result_wire(
        monitor_id=str(meta.get("monitor_id") or ""),
        monitor_state=monitor_state,
        exit_code=exit_code,
        command=str(meta.get("monitor_command") or ""),
        cwd=str(meta.get("monitor_cwd") or ""),
        started_at=meta.get("run_started_at"),
        stopped_at=meta.get("stopped_at"),
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=float(meta.get("monitor_timeout_seconds") or 0.0),
        timeout_kind=timeout_kind or meta.get("monitor_timeout_kind"),
        starter_execution_id=_clean_str(meta.get("monitor_starter_agent"))
        or _clean_str(meta.get("parent_timestamp")),
        workspace_identity=_clean_str(meta.get("continuation_workspace_ref"))
        or _clean_str(meta.get("workspace_dir")),
        diagnostic_manifest_ref=manifest.get("manifest_ref"),
        retained_log=retained_log,
    )
    evidence_selection = select_monitor_result_evidence(
        monitor_result,
        next_output=next_output,
        diagnostic_manifest=manifest,
    )
    selected_diagnostics = read_selected_diagnostics_text(
        artifacts_dir,
        selection=evidence_selection,
        manifest=manifest,
    )
    result_id = str(monitor_result.get("result_id") or "")
    branch = str(monitor_result.get("outcome") or "failed")
    if result_id:
        meta["continuation_monitor_result_id"] = result_id
        update_meta_field(artifacts_dir, "continuation_monitor_result_id", result_id)

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
        "next_output": next_output,
        "output_log_path": str(monitor_log_path(artifacts_dir)),
        "model": _clean_str(meta.get("model")),
        "reasoning_effort": _clean_str(meta.get("reasoning_effort")),
        "next_model": _clean_str(meta.get("monitor_next_model")),
        "diagnostic_manifest": manifest,
        "retained_log_metadata": retained_log,
        "evidence_selection": evidence_selection,
        "selected_diagnostics_text": selected_diagnostics.text,
        "starter_execution_id": _clean_str(meta.get("monitor_starter_agent"))
        or _clean_str(meta.get("parent_timestamp")),
        "workspace_identity": _clean_str(meta.get("continuation_workspace_ref"))
        or _clean_str(meta.get("workspace_dir")),
    }

    def _compose(degraded_reason: str | None) -> str:
        prompt = compose_followup_prompt(
            **prompt_kwargs, workspace_degraded_reason=degraded_reason
        )
        prefix = queue_launch_prefix(meta)
        return f"{prefix}{prompt}" if prefix else prompt

    try:
        resolved_plan = resolve_family_attach_plan(
            FamilyAttachDirective(parent=lane, suffix="@"),
            project_name=project_name,
        )
    except (FamilyAttachError, RuntimeError, OSError, ValueError) as exc:
        return _record_not_launchable(artifacts_dir, meta, str(exc), _compose(None))

    reserved_name = resolved_plan.agent_name
    claim = claim_ordinary_continuation_dispatch(
        artifacts_dir,
        monitor_id=str(meta.get("monitor_id") or "monitor"),
        result_id=result_id or "result",
        branch=branch,
        selected_action="continue",
        reserved_identity=reserved_name,
        extra=launch_wire_extra(meta),
    )
    if not claim.spawn:
        if claim.error:
            return _record_not_launchable(
                artifacts_dir, meta, claim.error, _compose(None)
            )
        return _record_launched(
            artifacts_dir,
            meta,
            claim.identity or reserved_name,
        )

    frozen_name = claim.identity or reserved_name
    frozen_plan = replace(
        resolved_plan,
        agent_name=frozen_name,
        parent_is_running=False,
        agent_family_role=starter_role or resolved_plan.agent_family_role,
    )
    delivery_env = continuation_delivery_env(artifacts_dir, claim.key, frozen_name)

    def _spawn(
        prompt: str,
        workspace_dir: str,
        workspace_num: int,
        transfer_pid: int | None,
        vcs_ref: tuple[str, str] | None,
    ) -> Any:
        maybe_crash("before_spawn")
        result = spawn_family_successor(
            FamilyAttachDirective(parent=lane, suffix="@"),
            project_name=project_name,
            prompt=prompt,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            transfer_from_pid=transfer_pid,
            cl_name=_clean_str(meta.get("cl_name")),
            agent_family_role=starter_role,
            vcs_ref=vcs_ref,
            extra_env=delivery_env,
            spawn_fn=spawn_agent_subprocess,
            resolve_plan=lambda *args, **kwargs: replace(
                frozen_plan,
                parent_workspace_dir=workspace_dir or frozen_plan.parent_workspace_dir,
                parent_workspace_num=workspace_num,
            ),
        )
        maybe_crash("after_spawn")
        update_delivery_workspace(
            artifacts_dir,
            claim.key,
            workspace_identity=workspace_dir,
        )
        return result

    monitor_artifacts_dir = artifacts_dir

    def _record_launched_result(
        agent_name: str | None,
        *,
        degraded_reason: str | None = None,
        artifacts_dir: str | None = None,
        pid: int | None = None,
    ) -> FollowupLaunchResult:
        if degraded_reason:
            update_delivery_workspace(
                monitor_artifacts_dir,
                claim.key,
                workspace_identity=None,
                workspace_degraded=True,
            )
        return _record_launched(
            monitor_artifacts_dir,
            meta,
            agent_name or frozen_name,
            degraded_reason=degraded_reason,
            launched_artifacts_dir=artifacts_dir,
            pid=pid,
        )

    def _record_not_launchable_result(error: str, prompt: str) -> FollowupLaunchResult:
        mark_ordinary_continuation_terminal(
            artifacts_dir,
            claim.key,
            "nonlaunchable",
            selected_action="continue",
            reason=error,
            reserved_identity=frozen_name,
        )
        return _record_not_launchable(artifacts_dir, meta, error, prompt)

    transfer_pid = os.getpid() if transfer_from_pid is None else transfer_from_pid
    return launch_shell_followup(
        project_name=project_name,
        meta_workspace_num=meta.get("workspace_num"),
        meta_workspace_dir=str(meta.get("workspace_dir") or ""),
        transfer_from_pid=transfer_pid,
        compose_prompt=_compose,
        spawn=_spawn,
        recorded_vcs_ref=vcs_ref_from_meta(meta),
        workspace=ShellFollowupWorkspace(
            meta_pairing_reason=_meta_pairing_degraded_reason,
            fresh_claim_reason=_fresh_claim_degraded_reason,
            pool_claim_reason=_pool_claim_degraded_reason,
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
    launched_artifacts_dir: str | None = None,
    pid: int | None = None,
) -> FollowupLaunchResult:
    return record_followup_launched(
        artifacts_dir,
        meta,
        agent_name=agent_name,
        degraded_reason=degraded_reason,
        launched_artifacts_dir=launched_artifacts_dir,
        pid=pid,
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


def _pool_claim_degraded_reason(
    workspace_num: int,
    error: BaseException,
    pool_workspace_num: int,
    pool_workspace_dir: str,
) -> str:
    return (
        f"The monitor workspace claim transfer failed, and workspace #{workspace_num} "
        f"could not be freshly claimed because it is already claimed: {error}. "
        f"The follow-up was launched in freshly claimed workspace #{pool_workspace_num} "
        f"({pool_workspace_dir}) instead. The prompt carries a VCS workflow tag, "
        "so the successor will run workspace setup there instead of using the "
        "monitored command's original workspace."
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
