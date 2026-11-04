"""Workspace-claim fallback chain for turn follow-up launches."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sase.agent.launch_types import AgentLaunchResult
from sase.running_field import (
    WorkspaceClaim,
    WorkspaceClaimError,
    claim_next_axe_workspace_dir,
    get_claimed_workspaces,
    get_workspace_directory_for_num,
    release_workspace,
)
from sase.workflows.utils import get_project_file_path
from sase.workspace_provider import resolve_consistent_workspace_pair

from ._followup_common import FollowupLaunchResult

_POOL_FOLLOWUP_CLAIM_WORKFLOW = "ace-followup"


@dataclass(frozen=True, slots=True)
class TurnFollowupWorkspace:
    """Messages a turn kind supplies for each degraded workspace outcome."""

    meta_pairing_reason: Callable[[str, str], str]
    fresh_claim_reason: Callable[[int, BaseException], str]
    pool_claim_reason: Callable[[int, BaseException, int, str], str]
    workspace_zero_reason: Callable[[int, BaseException, str], str]


def vcs_ref_from_meta(meta: Mapping[str, object]) -> tuple[str, str] | None:
    """Return the starter VCS workflow ref recorded on turn member *meta*."""
    raw = meta.get("vcs_ref")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        workflow, ref = raw
        if isinstance(workflow, str) and workflow and isinstance(ref, str) and ref:
            return workflow, ref
    return None


def _vcs_ref_from_prompt(prompt: str) -> tuple[str, str] | None:
    """Recover a VCS workflow ref from *prompt* via the registry tag pattern.

    Uses :func:`sase.workspace_provider.get_embedded_vcs_tag_pattern` to find
    a live ``#gh:``/``#git:`` tag anywhere in the composed prompt, then parses
    that tag with the launcher's ref patterns. Returns ``None`` when no
    registered VCS workflow is present.
    """
    from sase.workspace_provider import get_embedded_vcs_tag_pattern, get_ref_patterns

    if "+" in prompt:
        # Resolve project tags first so tag-form prompts recover correctly.
        try:
            from sase.project_tags import expand_project_tags

            prompt = expand_project_tags(prompt)
        except Exception:  # noqa: BLE001 - fall back to the raw prompt.
            pass
    match = get_embedded_vcs_tag_pattern().search(prompt)
    if match is None:
        return None
    tag = match.group(0)
    for workflow, pattern in get_ref_patterns().items():
        parsed = pattern.search(tag)
        if parsed is None:
            continue
        ref_value = parsed.group(1) or parsed.group(2)
        if ref_value:
            return workflow, ref_value
    return None


def _resolve_turn_followup_vcs_ref(
    recorded: tuple[str, str] | None,
    prompt: str,
) -> tuple[str, str] | None:
    """Choose the VCS ref a follow-up spawn should pre-allocate.

    Pre-allocation is only useful when the composed prompt still carries a
    VCS tag that will run setup. Prefer the starter's recorded
    ``(workflow, ref)`` when its workflow type matches the tag; otherwise
    recover the tag from the prompt. Older shells with no recorded ref fall
    through to prompt recovery. Returns ``None`` when there is no VCS
    workflow to pre-allocate for.
    """
    prompt_ref = _vcs_ref_from_prompt(prompt)
    if prompt_ref is None:
        return None
    if recorded is not None and recorded[0] == prompt_ref[0]:
        return recorded
    return prompt_ref


def _strict_workspace_pair_error(
    project_name: str,
    meta_workspace_num: object,
    meta_workspace_dir: str,
) -> str | None:
    """Validate a positive workspace pair before a strict follow-up spawn.

    Returns an error message when the pair is not usable, else ``None``.
    Strict follow-ups (keep-work recovery successors) must run in the exact
    positive workspace number **and** directory: they may never degrade to a
    pool workspace or workspace ``#0``.
    """
    if (
        not isinstance(meta_workspace_num, int)
        or isinstance(meta_workspace_num, bool)
        or meta_workspace_num <= 0
    ):
        return (
            "strict follow-up requires a positive workspace number, "
            f"got {meta_workspace_num!r}"
        )
    if not isinstance(meta_workspace_dir, str) or not meta_workspace_dir.strip():
        return (
            "strict follow-up requires a workspace directory, "
            f"got {meta_workspace_dir!r}"
        )
    try:
        canonical_dir = _workspace_dir_for_num(project_name, meta_workspace_num)
    except (RuntimeError, OSError, ValueError):
        # The canonical directory is not resolvable here; positivity of the
        # pair is the check this layer can still enforce.
        return None
    import os as _os

    if _os.path.normpath(canonical_dir) != _os.path.normpath(meta_workspace_dir):
        return (
            f"strict follow-up workspace metadata mismatch: workspace "
            f"#{meta_workspace_num} resolves to {canonical_dir}, "
            f"not {meta_workspace_dir}"
        )
    return None


def launch_turn_followup(
    *,
    project_name: str,
    meta_workspace_num: object,
    meta_workspace_dir: str,
    transfer_from_pid: int | None,
    compose_prompt: Callable[[str | None], str],
    spawn: Callable[
        [str, str, int, int | None, tuple[str, str] | None], AgentLaunchResult
    ],
    workspace: TurnFollowupWorkspace,
    record_launched: Callable[..., FollowupLaunchResult],
    record_not_launchable: Callable[[str, str], FollowupLaunchResult],
    recorded_vcs_ref: tuple[str, str] | None = None,
    strict_workspace: bool = False,
) -> FollowupLaunchResult:
    """Launch a follow-up agent, degrading through workspace claim fallbacks.

    Tries, in order: (1) transferring or freshly claiming the member's own
    workspace, composing the prompt without a degraded-workspace note; (2) on
    a claim failure, a fresh claim on the same workspace number, composing the
    prompt with a degraded-workspace note explaining the transfer failed; (3)
    for VCS-tagged follow-ups, a freshly claimed pool workspace; (4) for
    non-VCS follow-ups, workspace ``#0``, unless the original workspace turns
    out not to be claimed at all -- an unrecoverable state reported as not
    launchable instead. Every terminal outcome is recorded through
    *record_launched* / *record_not_launchable*.

    ``recorded_vcs_ref`` is the starter VCS workflow ref stored on the shell
    member. Each spawn attempt resolves it against the composed prompt and
    forwards the result so pre-allocation env describes the workspace that
    spawn actually used, including degraded ``#0`` fallbacks.

    When *strict_workspace* is true (keep-work recovery successors), the
    positive workspace pair is validated before spawn, only transfer and one
    fresh claim on that same pair are attempted, and any further failure is
    reported through *record_not_launchable*: pool-workspace and ``#0``
    fallbacks are never used.
    """
    if strict_workspace:
        pair_error = _strict_workspace_pair_error(
            project_name, meta_workspace_num, meta_workspace_dir
        )
        if pair_error is not None:
            return record_not_launchable(pair_error, compose_prompt(None))
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
    vcs_ref = _resolve_turn_followup_vcs_ref(recorded_vcs_ref, prompt)

    try:
        result = spawn(
            prompt,
            original_workspace_dir,
            original_workspace_num,
            transfer_from_pid,
            vcs_ref,
        )
    except WorkspaceClaimError as transfer_exc:
        fresh_reason = workspace.fresh_claim_reason(
            original_workspace_num, transfer_exc
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return record_not_launchable(str(exc), prompt)
    else:
        return record_launched(
            result.agent_name,
            degraded_reason=initial_degraded_reason,
            artifacts_dir=result.artifacts_dir or None,
            pid=result.pid,
        )

    degraded_prompt = compose_prompt(fresh_reason)
    degraded_vcs_ref = _resolve_turn_followup_vcs_ref(recorded_vcs_ref, degraded_prompt)
    try:
        result = spawn(
            degraded_prompt,
            original_workspace_dir,
            original_workspace_num,
            None,
            degraded_vcs_ref,
        )
    except WorkspaceClaimError as claim_exc:
        if strict_workspace:
            # Strict recovery successors stay on their exact workspace pair:
            # a failed transfer gets one same-pair fresh claim, and a second
            # failure is terminal -- never a pool workspace or workspace #0.
            error = (
                f"{claim_exc}; strict follow-up keeps workspace "
                f"#{original_workspace_num} ({original_workspace_dir}) after "
                f"transfer failure was prepared "
                f"with degraded reason: {fresh_reason}"
            )
            return record_not_launchable(error, degraded_prompt)
        if not _workspace_is_claimed(project_name, original_workspace_num):
            error = (
                f"{claim_exc}; follow-up prompt after transfer failure was prepared "
                f"with degraded reason: {fresh_reason}"
            )
            return record_not_launchable(error, degraded_prompt)
        if degraded_vcs_ref is not None:
            return _launch_vcs_followup_in_pool_workspace(
                project_name=project_name,
                original_workspace_num=original_workspace_num,
                claim_error=claim_exc,
                compose_prompt=compose_prompt,
                spawn=spawn,
                workspace=workspace,
                record_launched=record_launched,
                record_not_launchable=record_not_launchable,
                recorded_vcs_ref=recorded_vcs_ref,
                pool_failure_prompt=degraded_prompt,
            )
        zero_workspace_dir = _workspace_dir_for_num(project_name, 0)
        zero_reason = workspace.workspace_zero_reason(
            original_workspace_num, claim_exc, zero_workspace_dir
        )
        zero_prompt = compose_prompt(zero_reason)
        zero_vcs_ref = _resolve_turn_followup_vcs_ref(recorded_vcs_ref, zero_prompt)
        try:
            result = spawn(zero_prompt, zero_workspace_dir, 0, None, zero_vcs_ref)
        except (RuntimeError, OSError, ValueError) as exc:
            return record_not_launchable(str(exc), zero_prompt)
        return record_launched(
            result.agent_name,
            degraded_reason=zero_reason,
            artifacts_dir=result.artifacts_dir or None,
            pid=result.pid,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return record_not_launchable(str(exc), degraded_prompt)

    return record_launched(
        result.agent_name,
        degraded_reason=fresh_reason,
        artifacts_dir=result.artifacts_dir or None,
        pid=result.pid,
    )


def _launch_vcs_followup_in_pool_workspace(
    *,
    project_name: str,
    original_workspace_num: int,
    claim_error: WorkspaceClaimError,
    compose_prompt: Callable[[str | None], str],
    spawn: Callable[
        [str, str, int, int | None, tuple[str, str] | None], AgentLaunchResult
    ],
    workspace: TurnFollowupWorkspace,
    record_launched: Callable[..., FollowupLaunchResult],
    record_not_launchable: Callable[[str, str], FollowupLaunchResult],
    recorded_vcs_ref: tuple[str, str] | None,
    pool_failure_prompt: str,
) -> FollowupLaunchResult:
    project_file = get_project_file_path(project_name)
    holder_pid = os.getpid()
    try:
        pool_workspace_num, pool_workspace_dir, _ = claim_next_axe_workspace_dir(
            project_file,
            _POOL_FOLLOWUP_CLAIM_WORKFLOW,
            holder_pid,
            project_name,
            caller_tag="turn-followup-pool",
        )
    except WorkspaceClaimError as pool_exc:
        error = (
            f"{pool_exc}; original workspace #{original_workspace_num} was still "
            f"claimed after the same-workspace fresh claim failed: {claim_error}"
        )
        return record_not_launchable(error, pool_failure_prompt)

    pool_reason = workspace.pool_claim_reason(
        original_workspace_num,
        claim_error,
        pool_workspace_num,
        pool_workspace_dir,
    )
    pool_prompt = compose_prompt(pool_reason)
    pool_vcs_ref = _resolve_turn_followup_vcs_ref(recorded_vcs_ref, pool_prompt)
    try:
        result = spawn(
            pool_prompt,
            pool_workspace_dir,
            pool_workspace_num,
            holder_pid,
            pool_vcs_ref,
        )
    except (WorkspaceClaimError, RuntimeError, OSError, ValueError) as exc:
        release_result = release_workspace(
            project_file,
            pool_workspace_num,
            _POOL_FOLLOWUP_CLAIM_WORKFLOW,
            caller_tag="turn-followup-pool",
        )
        error = str(exc)
        if not release_result.success:
            error = (
                f"{error}; failed to release follow-up pool workspace "
                f"#{pool_workspace_num}: {release_result.error or 'unknown reason'}"
            )
        return record_not_launchable(error, pool_prompt)

    return record_launched(
        result.agent_name,
        degraded_reason=pool_reason,
        artifacts_dir=result.artifacts_dir or None,
        pid=result.pid,
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


__all__ = [
    "TurnFollowupWorkspace",
    "launch_turn_followup",
    "vcs_ref_from_meta",
]
