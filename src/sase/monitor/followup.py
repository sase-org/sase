"""Launch the follow-up agent into a monitor's lane once it goes terminal.

Reuses the same ``%id(<suffix>, family=<parent>)`` family-attach machinery a
user-typed directive would trigger (:mod:`sase.agent.family_attach`): the
monitor's lane is resolved to a family-attach plan, encoded into the child's
launch environment, and the child's own runner boot adopts the resulting name,
family, and role when it starts -- exactly as it would for an interactive
``%id(@, family=acme)`` launch.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import os
from typing import Any

from sase.agent._family_attach_resolution import resolve_family_attach_plan
from sase.agent._family_attach_types import FamilyAttachDirective, FamilyAttachError
from sase.agent.detached_child import spawn_family_successor
from sase.agent.launcher import spawn_agent_subprocess
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.continuation_capture.rollout import (
    monitor_continuation_records_enabled_for_meta,
)
from sase.shells.followup import (
    DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS,
    STARTER_SETTLE_POLL_SECONDS as _STARTER_SETTLE_POLL_SECONDS,
    FollowupLaunchResult,
    ShellFollowupWorkspace,
    launch_shell_followup,
    vcs_ref_from_meta,
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
from .followup_continuation import (
    frozen_intent_vcs_prefix as _frozen_intent_vcs_prefix,
    has_frozen_monitor_result_pointer as _has_frozen_monitor_result_pointer,
    load_checkpoint_body as _load_checkpoint_body,
    load_frozen_monitor_intent as _load_frozen_monitor_intent,
    load_frozen_monitor_result,
    next_action_from_intent as _next_action_from_intent,
    next_model_from_intent as _next_model_from_intent,
)
from .followup_output import frozen_output_text as _frozen_output_text
from .followup_persistence import (
    clean_str as _clean_str,
    fresh_claim_degraded_reason as _fresh_claim_degraded_reason,
    meta_pairing_degraded_reason as _meta_pairing_degraded_reason,
    monitor_starter_identity as _starter_identity,
    pool_claim_degraded_reason as _pool_claim_degraded_reason,
    record_launched as _record_launched,
    record_not_launchable as _record_not_launchable,
    recovery_prompt as _recovery_prompt,
    wait_for_monitor_starter,
    workspace_zero_degraded_reason as _workspace_zero_degraded_reason,
)
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
    retained_log_is_truncated,
    retained_log_locator_for_monitor_result,
    retained_log_total_bytes,
    select_monitor_result_evidence,
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
    branch_override: str | None = None,
    next_model_override: str | None = None,
    checkpoint_ref_override: str | None = None,
    retryable_pre_dispatch_failure: bool = False,
) -> FollowupLaunchResult:
    """Launch the agent named by ``monitor_next_action`` into the same lane.

    Returns the launch disposition. On failure, ``monitor_followup_error`` is
    recorded on the monitor member's own metadata; the caller is responsible
    for releasing the workspace claim and notifying.
    """
    records_enabled = monitor_continuation_records_enabled_for_meta(meta)
    intent: Mapping[str, Any] | None = None
    try:
        intent = _load_frozen_monitor_intent(artifacts_dir, meta)
    except ValueError as exc:
        if records_enabled:
            return _record_not_launchable(
                artifacts_dir,
                meta,
                str(exc),
                _recovery_prompt(str(exc)),
            )
        intent = None
    if (
        records_enabled
        and intent is None
        and _clean_str(meta.get("continuation_intent_ref"))
    ):
        error = (
            "frozen monitor intent could not be loaded from continuation metadata; "
            "manual recovery is required"
        )
        return _record_not_launchable(
            artifacts_dir,
            meta,
            error,
            _recovery_prompt(error),
        )

    next_action = _next_action_from_intent(intent) or str(
        meta.get("monitor_next_action") or ""
    )
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
    try:
        loaded_monitor_result = load_frozen_monitor_result(artifacts_dir, meta)
    except ValueError as exc:
        if records_enabled:
            return _record_not_launchable(
                artifacts_dir,
                meta,
                str(exc),
                _recovery_prompt(str(exc)),
            )
        raise
    if (
        records_enabled
        and loaded_monitor_result is None
        and _has_frozen_monitor_result_pointer(meta)
    ):
        error = (
            "frozen monitor result could not be loaded from continuation metadata; "
            "manual recovery is required"
        )
        return _record_not_launchable(
            artifacts_dir,
            meta,
            error,
            _recovery_prompt(error),
        )
    monitor_result: Mapping[str, Any]
    if loaded_monitor_result is None:
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
    else:
        monitor_result = loaded_monitor_result
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
    output_text = (
        _frozen_output_text(
            artifacts_dir,
            result=monitor_result,
            selection=evidence_selection,
            fallback=capture.retained_text(),
        )
        if loaded_monitor_result is not None
        else capture.retained_text()
    )
    result_id = str(monitor_result.get("result_id") or "")
    branch = branch_override or str(monitor_result.get("outcome") or "failed")
    if records_enabled and result_id:
        meta["continuation_monitor_result_id"] = result_id
        update_meta_field(artifacts_dir, "continuation_monitor_result_id", result_id)
    if records_enabled and checkpoint_ref_override:
        meta["continuation_checkpoint_ref"] = checkpoint_ref_override
        update_meta_field(
            artifacts_dir,
            "continuation_checkpoint_ref",
            checkpoint_ref_override,
        )
    selected_next_model = (
        next_model_override
        or _next_model_from_intent(intent)
        or _clean_str(meta.get("monitor_next_model"))
    )
    vcs_prefix = _frozen_intent_vcs_prefix(meta, frozen_next_action=next_action)
    checkpoint_ref = (
        checkpoint_ref_override
        or _clean_str((intent or {}).get("checkpoint_ref"))
        or _clean_str(meta.get("continuation_checkpoint_ref"))
    )
    checkpoint_body = _load_checkpoint_body(artifacts_dir, checkpoint_ref)
    output_log_path = str(monitor_log_path(artifacts_dir))
    total_bytes = capture.total_bytes
    output_truncated = capture.truncated
    retained_for_prompt = retained_log
    if loaded_monitor_result is not None:
        retained = monitor_result.get("retained_log")
        retained_for_prompt = dict(retained) if isinstance(retained, Mapping) else {}
        output_log_path = (
            retained_log_locator_for_monitor_result(
                monitor_result,
                fallback=output_log_path,
            )
            or output_log_path
        )
        total_bytes = retained_log_total_bytes(
            monitor_result,
            fallback=capture.total_bytes,
        )
        output_truncated = retained_log_is_truncated(
            monitor_result,
            fallback=capture.truncated,
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
        "output_text": output_text,
        "tail_lines": int(meta.get("monitor_tail_lines") or 200),
        "total_bytes": total_bytes,
        "output_truncated": output_truncated,
        "next_action": next_action,
        "next_output": next_output,
        "output_log_path": output_log_path,
        "model": _clean_str(meta.get("model")),
        "reasoning_effort": _clean_str(meta.get("reasoning_effort")),
        "next_model": selected_next_model,
        "diagnostic_manifest": manifest,
        "retained_log_metadata": retained_for_prompt,
        "evidence_selection": evidence_selection,
        "selected_diagnostics_text": selected_diagnostics.text,
        "starter_execution_id": _clean_str(meta.get("monitor_starter_agent"))
        or _clean_str(meta.get("parent_timestamp")),
        "workspace_identity": _clean_str(meta.get("continuation_workspace_ref"))
        or _clean_str(meta.get("workspace_dir")),
        "monitor_result": monitor_result if loaded_monitor_result is not None else None,
        "checkpoint_ref": checkpoint_ref,
        "checkpoint_body": checkpoint_body,
    }

    def _compose(degraded_reason: str | None) -> str:
        prompt = compose_followup_prompt(
            **prompt_kwargs, workspace_degraded_reason=degraded_reason
        )
        prefix = queue_launch_prefix(meta)
        return f"{prefix}{vcs_prefix}{prompt}" if prefix or vcs_prefix else prompt

    try:
        resolved_plan = resolve_family_attach_plan(
            FamilyAttachDirective(parent=lane, suffix="@"),
            project_name=project_name,
        )
    except (FamilyAttachError, RuntimeError, OSError, ValueError) as exc:
        return _record_not_launchable(artifacts_dir, meta, str(exc), _compose(None))

    reserved_name = resolved_plan.agent_name
    claim_key: Mapping[str, Any] | None = None
    if records_enabled:
        claim = claim_ordinary_continuation_dispatch(
            artifacts_dir,
            monitor_id=str(meta.get("monitor_id") or "monitor"),
            result_id=result_id or "result",
            branch=branch,
            selected_action="continue",
            reserved_identity=reserved_name,
            extra=launch_wire_extra(meta),
            retryable_pre_dispatch_failure=retryable_pre_dispatch_failure,
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
        claim_key = claim.key
        delivery_env = continuation_delivery_env(artifacts_dir, claim.key, frozen_name)
    else:
        frozen_name = reserved_name
        delivery_env = None
    frozen_plan = replace(
        resolved_plan,
        agent_name=frozen_name,
        parent_is_running=False,
        agent_family_role=starter_role or resolved_plan.agent_family_role,
    )

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
        if claim_key is not None:
            update_delivery_workspace(
                artifacts_dir,
                claim_key,
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
        if degraded_reason and claim_key is not None:
            update_delivery_workspace(
                monitor_artifacts_dir,
                claim_key,
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
        if claim_key is not None:
            mark_ordinary_continuation_terminal(
                artifacts_dir,
                claim_key,
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
    return wait_for_monitor_starter(
        project_name,
        parent_timestamp,
        timeout_seconds=timeout_seconds,
        poll_seconds=_STARTER_SETTLE_POLL_SECONDS,
    )


__all__ = [
    "DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS",
    "FollowupLaunchResult",
    "load_frozen_monitor_result",
    "launch_followup_agent",
]
