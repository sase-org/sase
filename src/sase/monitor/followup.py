"""Launch the follow-up agent into a monitor's lane once it goes terminal.

Reuses the same ``%id(<suffix>, family=<parent>)`` family-attach machinery a
user-typed directive would trigger (:mod:`sase.agent.family_attach`): the
monitor's lane is resolved to a family-attach plan, encoded into the child's
launch environment, and the child's own runner boot adopts the resulting name,
family, and role when it starts -- exactly as it would for an interactive
``%id(@, family=acme)`` launch.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from sase.agent.family_attach import (
    FAMILY_ATTACH_ENV,
    FamilyAttachDirective,
    FamilyAttachError,
    resolve_family_attach_plan,
)
from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.agent.launcher import spawn_agent_subprocess
from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.agent_launch_facade import reserve_launch_timestamp_batch
from sase.core.artifact_file_facade import store_explicit_artifact_file
from sase.running_field import (
    WorkspaceClaim,
    WorkspaceClaimError,
    get_claimed_workspaces,
    get_workspace_directory_for_num,
)
from sase.workflows.utils import get_project_file_path

from .followup_prompt import DEFAULT_NEXT_OUTPUT, compose_followup_prompt
from .logs import monitor_log_path
from .output import OutputCapture

#: How long to wait for the starter's own ``done.json`` before composing the
#: follow-up prompt without a ``#fork:`` prefix. Injectable so tests do not
#: have to wait out the real budget for the common "no starter" case.
DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS = 60.0
_STARTER_SETTLE_POLL_SECONDS = 0.5
_SAVED_FOLLOWUP_PROMPT_NAME = "monitor_followup_prompt.md"


@dataclass(frozen=True)
class FollowupLaunchResult:
    """Outcome of attempting to launch a monitor follow-up agent."""

    launched: bool
    degraded_reason: str | None = None
    error: str | None = None
    prompt_path: str | None = None
    agent_name: str | None = None

    def __bool__(self) -> bool:
        return self.launched


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
    }
    prompt = compose_followup_prompt(
        **prompt_kwargs,
        workspace_degraded_reason=None,
    )

    try:
        plan = resolve_family_attach_plan(
            FamilyAttachDirective(parent=lane, suffix="@"),
            project_name=project_name,
        )
    except FamilyAttachError as exc:
        return _record_not_launchable(artifacts_dir, meta, str(exc), prompt)

    original_workspace_num = int(meta.get("workspace_num") or 0)
    original_workspace_dir = str(meta.get("workspace_dir") or "")
    transfer_pid = os.getpid() if transfer_from_pid is None else transfer_from_pid
    try:
        result = _spawn_followup(
            meta,
            plan=plan,
            starter_role=starter_role,
            project_name=project_name,
            prompt=prompt,
            workspace_dir=original_workspace_dir,
            workspace_num=original_workspace_num,
            transfer_from_pid=transfer_pid,
        )
    except WorkspaceClaimError as transfer_exc:
        fresh_reason = _fresh_claim_degraded_reason(
            original_workspace_num,
            transfer_exc,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return _record_not_launchable(artifacts_dir, meta, str(exc), prompt)
    else:
        return _record_launched(
            artifacts_dir,
            meta,
            result.agent_name or plan.agent_name,
        )

    degraded_prompt = compose_followup_prompt(
        **prompt_kwargs,
        workspace_degraded_reason=fresh_reason,
    )
    try:
        result = _spawn_followup(
            meta,
            plan=plan,
            starter_role=starter_role,
            project_name=project_name,
            prompt=degraded_prompt,
            workspace_dir=original_workspace_dir,
            workspace_num=original_workspace_num,
            transfer_from_pid=None,
        )
    except WorkspaceClaimError as claim_exc:
        if not _workspace_is_claimed(project_name, original_workspace_num):
            error = (
                f"{claim_exc}; follow-up prompt after transfer failure was prepared "
                f"with degraded reason: {fresh_reason}"
            )
            return _record_not_launchable(artifacts_dir, meta, error, degraded_prompt)
        zero_reason = _workspace_zero_degraded_reason(
            original_workspace_num,
            claim_exc,
        )
        zero_prompt = compose_followup_prompt(
            **prompt_kwargs,
            workspace_degraded_reason=zero_reason,
        )
        try:
            result = _spawn_followup(
                meta,
                plan=plan,
                starter_role=starter_role,
                project_name=project_name,
                prompt=zero_prompt,
                workspace_dir=_workspace_dir_for_num(project_name, 0),
                workspace_num=0,
                transfer_from_pid=None,
            )
        except (RuntimeError, OSError, ValueError) as exc:
            return _record_not_launchable(artifacts_dir, meta, str(exc), zero_prompt)
        return _record_launched(
            artifacts_dir,
            meta,
            result.agent_name or plan.agent_name,
            degraded_reason=zero_reason,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return _record_not_launchable(artifacts_dir, meta, str(exc), degraded_prompt)

    return _record_launched(
        artifacts_dir,
        meta,
        result.agent_name or plan.agent_name,
        degraded_reason=fresh_reason,
    )


def _spawn_followup(
    meta: dict[str, Any],
    *,
    plan: Any,
    starter_role: str | None,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
) -> Any:
    launch_plan = replace(
        plan,
        parent_is_running=False,
        agent_family_role=starter_role or plan.agent_family_role,
        parent_workspace_dir=workspace_dir or plan.parent_workspace_dir,
        parent_workspace_num=workspace_num,
    )
    env = {
        INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
        FAMILY_ATTACH_ENV: json.dumps(asdict(launch_plan), sort_keys=True),
    }
    timestamp = reserve_launch_timestamp_batch(1)[0]
    return spawn_agent_subprocess(
        cl_name=str(meta.get("cl_name") or launch_plan.agent_name),
        project_file=get_project_file_path(project_name),
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        workflow_name=f"ace(run)-{timestamp}",
        prompt=prompt,
        timestamp=timestamp,
        project_name=project_name,
        extra_env=env,
        retry_transfer_from_pid=transfer_from_pid,
    )


def _record_launched(
    artifacts_dir: str,
    meta: dict[str, Any],
    agent_name: str | None,
    *,
    degraded_reason: str | None = None,
) -> FollowupLaunchResult:
    if agent_name:
        meta["monitor_followup_agent"] = agent_name
        update_meta_field(artifacts_dir, "monitor_followup_agent", agent_name)
    if degraded_reason:
        meta["monitor_followup_degraded_reason"] = degraded_reason
        update_meta_field(
            artifacts_dir,
            "monitor_followup_degraded_reason",
            degraded_reason,
        )
    return FollowupLaunchResult(
        launched=True,
        degraded_reason=degraded_reason,
        agent_name=agent_name,
    )


def _record_not_launchable(
    artifacts_dir: str,
    meta: dict[str, Any],
    error: str,
    prompt: str,
) -> FollowupLaunchResult:
    prompt_path = _persist_unlaunchable_prompt(artifacts_dir, prompt)
    message = error
    if prompt_path:
        message = f"{error}; follow-up prompt saved to {prompt_path}"
        meta["monitor_followup_prompt_path"] = prompt_path
        update_meta_field(artifacts_dir, "monitor_followup_prompt_path", prompt_path)
    meta["monitor_followup_error"] = message
    update_meta_field(artifacts_dir, "monitor_followup_error", message)
    return FollowupLaunchResult(
        launched=False,
        error=message,
        prompt_path=prompt_path,
    )


def _persist_unlaunchable_prompt(artifacts_dir: str, prompt: str) -> str | None:
    try:
        artifacts_path = Path(artifacts_dir).expanduser()
        artifacts_path.mkdir(parents=True, exist_ok=True)
        prompt_path = artifacts_path / _SAVED_FOLLOWUP_PROMPT_NAME
        prompt_path.write_text(prompt, encoding="utf-8")
        store_explicit_artifact_file(
            prompt_path,
            artifacts_path,
            label="Unlaunched monitor follow-up prompt",
            kind="markdown",
        )
        return str(prompt_path)
    except Exception:
        return None


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
) -> str:
    return (
        f"The monitor workspace claim transfer failed, and workspace #{workspace_num} "
        f"could not be freshly claimed because it is already claimed: {error}. "
        "The follow-up was launched in workspace #0 instead. Do not assume the "
        "monitored command's workspace files are present; use the monitor artifacts "
        "and log paths in this prompt."
    )


def _workspace_is_claimed(project_name: str, workspace_num: int) -> bool:
    try:
        claims = get_claimed_workspaces(get_project_file_path(project_name))
    except Exception:
        return False
    return any(
        isinstance(claim, WorkspaceClaim) and claim.workspace_num == workspace_num
        for claim in claims
    )


def _workspace_dir_for_num(project_name: str, workspace_num: int) -> str:
    workspace_dir, _ = get_workspace_directory_for_num(
        workspace_num,
        project_name,
        clean=False,
    )
    return workspace_dir


def _clean_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _starter_artifacts_dir(project_name: str, parent_timestamp: object) -> str | None:
    if not isinstance(parent_timestamp, str) or not parent_timestamp:
        return None
    return str(canonical_agent_artifact_path(project_name, "ace-run", parent_timestamp))


def _read_meta_str(artifacts_dir: str, key: str) -> str | None:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def _starter_identity(
    project_name: str, parent_timestamp: object
) -> tuple[str | None, str | None]:
    starter_dir = _starter_artifacts_dir(project_name, parent_timestamp)
    if starter_dir is None:
        return None, None
    return (
        _read_meta_str(starter_dir, "name"),
        _read_meta_str(starter_dir, "agent_family_role"),
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
    starter_dir = _starter_artifacts_dir(project_name, parent_timestamp)
    if starter_dir is None:
        return False
    done_path = Path(starter_dir) / "done.json"
    deadline = time.monotonic() + timeout_seconds
    while not done_path.exists() and time.monotonic() < deadline:
        time.sleep(_STARTER_SETTLE_POLL_SECONDS)
    return done_path.exists()


__all__ = [
    "DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS",
    "FollowupLaunchResult",
    "launch_followup_agent",
]
