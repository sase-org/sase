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
from sase.running_field import (
    WorkspaceClaim,
    WorkspaceClaimError,
    get_claimed_workspaces,
    get_workspace_directory_for_num,
)
from sase.workflows.utils import get_project_file_path
from sase.workspace_provider import resolve_consistent_workspace_pair

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
class ShellFollowupWorkspace:
    """Messages a shell kind supplies for each degraded workspace outcome."""

    meta_pairing_reason: Callable[[str, str], str]
    fresh_claim_reason: Callable[[int, BaseException], str]
    workspace_zero_reason: Callable[[int, BaseException, str], str]


def launch_shell_followup(
    *,
    project_name: str,
    meta_workspace_num: object,
    meta_workspace_dir: str,
    transfer_from_pid: int | None,
    compose_prompt: Callable[[str | None], str],
    spawn: Callable[[str, str, int, int | None], AgentLaunchResult],
    workspace: ShellFollowupWorkspace,
    record_launched: Callable[..., FollowupLaunchResult],
    record_not_launchable: Callable[[str, str], FollowupLaunchResult],
) -> FollowupLaunchResult:
    """Launch a follow-up agent, degrading through workspace claim fallbacks.

    Tries, in order: (1) transferring or freshly claiming the member's own
    workspace, composing the prompt without a degraded-workspace note; (2) on
    a claim failure, a fresh claim on the same workspace number, composing the
    prompt with a degraded-workspace note explaining the transfer failed; (3)
    on a further claim failure, workspace ``#0``, unless the original
    workspace turns out not to be claimed at all -- an unrecoverable state
    reported as not launchable instead. Every terminal outcome is recorded
    through *record_launched* / *record_not_launchable*.
    """
    initial_degraded_reason: str | None = None
    if isinstance(meta_workspace_num, int) and meta_workspace_num:
        original_workspace_dir = meta_workspace_dir
        original_workspace_num = meta_workspace_num
    else:
        # Defensive default matching pre-repair behavior, in case resolving
        # the primary workspace directory itself fails below.
        original_workspace_dir = meta_workspace_dir
        original_workspace_num = 0
        try:
            primary_workspace_dir: str | None = _workspace_dir_for_num(project_name, 0)
        except (RuntimeError, OSError, ValueError):
            primary_workspace_dir = None
        if primary_workspace_dir is not None:
            resolved_pair = resolve_consistent_workspace_pair(
                primary_workspace_dir,
                meta_workspace_dir,
                None,
            )
            if resolved_pair is None:
                original_workspace_dir = primary_workspace_dir
                initial_degraded_reason = workspace.meta_pairing_reason(
                    meta_workspace_dir, primary_workspace_dir
                )
            else:
                original_workspace_dir, original_workspace_num = resolved_pair

    prompt = compose_prompt(initial_degraded_reason)

    try:
        result = spawn(
            prompt, original_workspace_dir, original_workspace_num, transfer_from_pid
        )
    except WorkspaceClaimError as transfer_exc:
        fresh_reason = workspace.fresh_claim_reason(
            original_workspace_num, transfer_exc
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return record_not_launchable(str(exc), prompt)
    else:
        return record_launched(
            result.agent_name, degraded_reason=initial_degraded_reason
        )

    degraded_prompt = compose_prompt(fresh_reason)
    try:
        result = spawn(
            degraded_prompt, original_workspace_dir, original_workspace_num, None
        )
    except WorkspaceClaimError as claim_exc:
        if not _workspace_is_claimed(project_name, original_workspace_num):
            error = (
                f"{claim_exc}; follow-up prompt after transfer failure was prepared "
                f"with degraded reason: {fresh_reason}"
            )
            return record_not_launchable(error, degraded_prompt)
        zero_workspace_dir = _workspace_dir_for_num(project_name, 0)
        zero_reason = workspace.workspace_zero_reason(
            original_workspace_num, claim_exc, zero_workspace_dir
        )
        zero_prompt = compose_prompt(zero_reason)
        try:
            result = spawn(zero_prompt, zero_workspace_dir, 0, None)
        except (RuntimeError, OSError, ValueError) as exc:
            return record_not_launchable(str(exc), zero_prompt)
        return record_launched(result.agent_name, degraded_reason=zero_reason)
    except (RuntimeError, OSError, ValueError) as exc:
        return record_not_launchable(str(exc), degraded_prompt)

    return record_launched(result.agent_name, degraded_reason=fresh_reason)


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
    suffix: str | None = None,
    agent_family_role: str | None = None,
    spawn_fn: SpawnFn | None = None,
) -> AgentLaunchResult:
    """Spawn the next agent member in *family* using family-attach semantics."""
    return spawn_family_successor(
        FamilyAttachDirective(parent=family, suffix=suffix or "@"),
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


def _clean_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


UpdateMetaFieldFn = Callable[[str, str, object], None]


__all__ = [
    "DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS",
    "STARTER_SETTLE_POLL_SECONDS",
    "FollowupLaunchResult",
    "FollowupPersistence",
    "ShellFollowupWorkspace",
    "fork_target_for_settled_starter",
    "launch_shell_followup",
    "persist_followup_prompt",
    "record_followup_launched",
    "record_followup_not_launchable",
    "spawn_shell_family_successor",
    "starter_identity",
    "wait_for_starter",
]
