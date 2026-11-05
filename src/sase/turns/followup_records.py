"""Persistence helpers for turn follow-up launches."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.agent.detached_child import (
    AgentSessionAttachDirective,
    SpawnFn,
    spawn_agent_session_successor,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.artifact_file_facade import store_explicit_artifact_file

from ._followup_common import FollowupLaunchResult

UpdateMetaFieldFn = Callable[[str, str, object], None]


@dataclass(frozen=True, slots=True)
class FollowupPersistence:
    """Metadata field names and artifact labels for persisted follow-up state."""

    agent_field: str
    error_field: str
    prompt_path_field: str
    degraded_reason_field: str
    prompt_filename: str
    prompt_label: str
    prompt_kind: str = "markdown"


def spawn_turn_agent_session_successor(
    *,
    agent_session: str,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    cl_name: str | None = None,
    suffix: str | None = None,
    agent_session_role: str | None = None,
    vcs_ref: tuple[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
    spawn_fn: SpawnFn | None = None,
    predecessor_artifacts_dir: str | None = None,
    predecessor_name: str | None = None,
) -> AgentLaunchResult:
    """Spawn the next agent member in *agent_session* using agent-session attach semantics."""
    return spawn_agent_session_successor(
        AgentSessionAttachDirective(parent=agent_session, suffix=suffix or "@"),
        project_name=project_name,
        prompt=prompt,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        transfer_from_pid=transfer_from_pid,
        cl_name=cl_name,
        agent_session_role=agent_session_role,
        vcs_ref=vcs_ref,
        extra_env=extra_env,
        spawn_fn=spawn_fn,
        predecessor_artifacts_dir=predecessor_artifacts_dir,
        predecessor_name=predecessor_name,
    )


def record_followup_launched(
    artifacts_dir: str,
    meta: dict[str, object],
    *,
    agent_name: str | None,
    persistence: FollowupPersistence,
    update_meta_field: UpdateMetaFieldFn,
    degraded_reason: str | None = None,
    launched_artifacts_dir: str | None = None,
    pid: int | None = None,
) -> FollowupLaunchResult:
    """Record a launched follow-up in metadata and return its result."""
    if agent_name:
        meta[persistence.agent_field] = agent_name
        update_meta_field(artifacts_dir, persistence.agent_field, agent_name)
    if degraded_reason:
        meta[persistence.degraded_reason_field] = degraded_reason
        update_meta_field(
            artifacts_dir,
            persistence.degraded_reason_field,
            degraded_reason,
        )
    return FollowupLaunchResult(
        launched=True,
        degraded_reason=degraded_reason,
        agent_name=agent_name,
        artifacts_dir=launched_artifacts_dir,
        pid=pid,
    )


def record_followup_not_launchable(
    artifacts_dir: str,
    meta: dict[str, object],
    *,
    error: str,
    prompt: str,
    persistence: FollowupPersistence,
    update_meta_field: UpdateMetaFieldFn,
) -> FollowupLaunchResult:
    """Persist an unlaunchable follow-up prompt and record the error."""
    prompt_path = persist_followup_prompt(artifacts_dir, prompt, persistence)
    message = error
    if prompt_path:
        message = f"{error}; follow-up prompt saved to {prompt_path}"
        meta[persistence.prompt_path_field] = prompt_path
        update_meta_field(artifacts_dir, persistence.prompt_path_field, prompt_path)
    meta[persistence.error_field] = message
    update_meta_field(artifacts_dir, persistence.error_field, message)
    return FollowupLaunchResult(
        launched=False,
        error=message,
        prompt_path=prompt_path,
    )


def persist_followup_prompt(
    artifacts_dir: str,
    prompt: str,
    persistence: FollowupPersistence,
) -> str | None:
    """Save *prompt* as an indexed artifact when it cannot be launched."""
    try:
        artifacts_path = Path(artifacts_dir).expanduser()
        artifacts_path.mkdir(parents=True, exist_ok=True)
        prompt_path = artifacts_path / persistence.prompt_filename
        prompt_path.write_text(prompt, encoding="utf-8")
        store_explicit_artifact_file(
            prompt_path,
            artifacts_path,
            label=persistence.prompt_label,
            kind=persistence.prompt_kind,
        )
        return str(prompt_path)
    except Exception:
        return None


__all__ = [
    "FollowupPersistence",
    "UpdateMetaFieldFn",
    "persist_followup_prompt",
    "record_followup_launched",
    "record_followup_not_launchable",
    "spawn_turn_agent_session_successor",
]
