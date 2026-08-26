"""Follow-up launch support shared by family shell kinds."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.agent.detached_child import (
    FamilyAttachDirective,
    SpawnFn,
    spawn_family_successor,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_artifact_paths import canonical_agent_artifact_path
from sase.core.artifact_file_facade import store_explicit_artifact_file
from sase.plan_chain import agent_family_base

#: How long to wait for the starter's own ``done.json`` before composing the
#: follow-up prompt without a ``#fork:`` prefix.
DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS = 60.0
STARTER_SETTLE_POLL_SECONDS = 0.5


@dataclass(frozen=True)
class FollowupLaunchResult:
    """Outcome of attempting to launch a shell follow-up agent."""

    launched: bool
    degraded_reason: str | None = None
    error: str | None = None
    prompt_path: str | None = None
    agent_name: str | None = None

    def __bool__(self) -> bool:
        return self.launched


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


def spawn_shell_family_successor(
    *,
    family: str,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    cl_name: str | None = None,
    agent_family_role: str | None = None,
    spawn_fn: SpawnFn | None = None,
) -> AgentLaunchResult:
    """Spawn the next agent member in *family* using family-attach semantics."""
    return spawn_family_successor(
        FamilyAttachDirective(parent=family, suffix="@"),
        project_name=project_name,
        prompt=prompt,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        transfer_from_pid=transfer_from_pid,
        cl_name=cl_name,
        agent_family_role=agent_family_role,
        spawn_fn=spawn_fn,
    )


def record_followup_launched(
    artifacts_dir: str,
    meta: dict[str, object],
    *,
    agent_name: str | None,
    persistence: FollowupPersistence,
    update_meta_field: UpdateMetaFieldFn,
    degraded_reason: str | None = None,
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
    prompt_path = _persist_unlaunchable_prompt(artifacts_dir, prompt, persistence)
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


def fork_target_for_settled_starter(
    *,
    starter_name: str | None,
    family_name: str | None,
    settled: bool,
) -> str | None:
    """Return the transcript target a settled follow-up should fork."""
    if not settled:
        return None
    family = _clean_str(family_name)
    if family:
        return family
    starter = _clean_str(starter_name)
    if not starter:
        return None
    return agent_family_base(starter) or starter


def starter_identity(
    project_name: str,
    parent_timestamp: object,
) -> tuple[str | None, str | None]:
    """Return ``(starter_name, starter_role)`` for a parent timestamp."""
    starter_dir = _starter_artifacts_dir(project_name, parent_timestamp)
    if starter_dir is None:
        return None, None
    return (
        _read_meta_str(starter_dir, "name"),
        _read_meta_str(starter_dir, "agent_family_role"),
    )


def wait_for_starter(
    project_name: str,
    parent_timestamp: object,
    *,
    timeout_seconds: float,
    poll_seconds: float = STARTER_SETTLE_POLL_SECONDS,
) -> bool:
    """Poll for the starter's terminal marker before forking its chat."""
    starter_dir = _starter_artifacts_dir(project_name, parent_timestamp)
    if starter_dir is None:
        return False
    done_path = Path(starter_dir) / "done.json"
    deadline = time.monotonic() + timeout_seconds
    while not done_path.exists() and time.monotonic() < deadline:
        time.sleep(poll_seconds)
    return done_path.exists()


def _starter_artifacts_dir(project_name: str, parent_timestamp: object) -> str | None:
    """Return the starter artifact path for *parent_timestamp*, if valid."""
    if not isinstance(parent_timestamp, str) or not parent_timestamp:
        return None
    return str(canonical_agent_artifact_path(project_name, "ace-run", parent_timestamp))


def _read_meta_str(artifacts_dir: str, key: str) -> str | None:
    """Read one string key from an artifact's ``agent_meta.json``."""
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def _persist_unlaunchable_prompt(
    artifacts_dir: str,
    prompt: str,
    persistence: FollowupPersistence,
) -> str | None:
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


def _clean_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


UpdateMetaFieldFn = Callable[[str, str, object], None]


__all__ = [
    "DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS",
    "STARTER_SETTLE_POLL_SECONDS",
    "FollowupLaunchResult",
    "FollowupPersistence",
    "fork_target_for_settled_starter",
    "record_followup_launched",
    "record_followup_not_launchable",
    "spawn_shell_family_successor",
    "starter_identity",
    "wait_for_starter",
]
