"""Persistence and workspace wording helpers for monitor follow-ups."""

from __future__ import annotations

from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.shells.followup import (
    FollowupLaunchResult,
    FollowupPersistence,
    record_followup_launched,
    record_followup_not_launchable,
    starter_identity,
    wait_for_starter,
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


def recovery_prompt(error: str) -> str:
    return (
        "%xprompts_enabled:false\n"
        "# Monitor continuation recovery required\n\n"
        "The versioned monitor continuation context could not be loaded. "
        "Do not reconstruct the monitored result from mutable metadata.\n\n"
        f"```text\n{error}\n```\n"
        "%xprompts_enabled:true"
    )


def record_launched(
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


def record_not_launchable(
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


def fresh_claim_degraded_reason(
    workspace_num: int,
    error: BaseException,
) -> str:
    return (
        f"The monitor workspace claim transfer failed for workspace #{workspace_num}: "
        f"{error}. The follow-up was launched by taking a fresh claim on the same "
        "workspace, so the monitored command's workspace should still be present."
    )


def workspace_zero_degraded_reason(
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


def pool_claim_degraded_reason(
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


def meta_pairing_degraded_reason(
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


def clean_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def monitor_starter_identity(
    project_name: str, parent_timestamp: object
) -> tuple[str | None, str | None]:
    return starter_identity(project_name, parent_timestamp)


def wait_for_monitor_starter(
    project_name: str,
    parent_timestamp: object,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> bool:
    """Poll for the starter's terminal marker before forking its chat."""
    return wait_for_starter(
        project_name,
        parent_timestamp,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )


__all__ = [
    "clean_str",
    "fresh_claim_degraded_reason",
    "meta_pairing_degraded_reason",
    "monitor_starter_identity",
    "pool_claim_degraded_reason",
    "record_launched",
    "record_not_launchable",
    "recovery_prompt",
    "wait_for_monitor_starter",
    "workspace_zero_degraded_reason",
]
