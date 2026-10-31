"""Monitor claim, follow-up, and refresh settlement facade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.continuation_capture.rollout import (
    monitor_continuation_records_enabled_for_meta,
)
from sase.turns.settlement import (
    TurnSettlementConfig,
    finalize_turn_workflow_state,
    project_name_from_artifacts_dir as shell_project_name_from_artifacts_dir,
    record_turn_followup_outcome,
    settle_turn_claim_and_followup,
    touch_turn_refresh_pulse,
)

from .followup import FollowupLaunchResult, launch_followup_agent
from .host_completion import HOST_COMPLETED_OUTCOME, settle_host_completion
from .models import MONITOR_FOLLOWUP_DEGRADED_OUTCOME, MonitorState
from .naming import short_monitor_id
from .output import OutputCapture
from .worktree_recovery import snapshot_worktree_recovery_diff

LOST_FOLLOWUP_ERROR = (
    "follow-up not launched because the monitor command outcome is unknown"
)

FollowupLauncher = Callable[..., bool | FollowupLaunchResult]

_MONITOR_SETTLEMENT_CONFIG = TurnSettlementConfig(
    next_action_field="monitor_next_action",
    agent_field="monitor_followup_agent",
    outcome_field="monitor_followup_outcome",
    error_field="monitor_followup_error",
    degraded_reason_field="monitor_followup_degraded_reason",
    prompt_path_field="monitor_followup_prompt_path",
    lost_state="lost",
    stopped_state="stopped",
    lost_followup_error=LOST_FOLLOWUP_ERROR,
    degraded_outcome=MONITOR_FOLLOWUP_DEGRADED_OUTCOME,
    fallback_followup_error="follow-up launch failed",
    missing_project_error=(
        "could not resolve the monitor's project from its artifacts path"
    ),
)


@dataclass(frozen=True, slots=True)
class _MonitorFollowupSettlementResult:
    """Disposition recorded while settling a monitor follow-up."""

    error: str | None = None
    launch_result: FollowupLaunchResult | None = None


def settle_claim_and_followup(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: MonitorState,
    exit_code: int | None,
    elapsed_seconds: float,
    capture: OutputCapture,
    timeout_kind: str | None,
    project_name: str | None,
    transfer_from_pid: int | None = None,
    launch_followup: FollowupLauncher | None = None,
) -> _MonitorFollowupSettlementResult:
    """Launch/record follow-up disposition and dispose of the monitor claim."""
    launcher = launch_followup or launch_followup_agent
    captured_launch_result: FollowupLaunchResult | None = None

    def launch_and_capture(*args: Any, **kwargs: Any) -> FollowupLaunchResult:
        nonlocal captured_launch_result
        raw = launcher(*args, **kwargs)
        captured_launch_result = _coerce_monitor_followup_result(raw, meta)
        return captured_launch_result

    if not monitor_continuation_records_enabled_for_meta(meta):
        error = settle_turn_claim_and_followup(
            artifacts_dir,
            meta,
            shell_state=monitor_state,
            project_name=project_name,
            config=_MONITOR_SETTLEMENT_CONFIG,
            release_claim=_make_retention_release_claim(artifacts_dir),
            launch_followup=launch_and_capture,
            launch_kwargs={
                "monitor_state": monitor_state,
                "exit_code": exit_code,
                "elapsed_seconds": elapsed_seconds,
                "capture": capture,
                "timeout_kind": timeout_kind,
                "project_name": project_name,
                "transfer_from_pid": transfer_from_pid,
            },
            update_meta_field=update_meta_field,
        )
        return _MonitorFollowupSettlementResult(
            error=error, launch_result=captured_launch_result
        )

    blocked_reason = None
    if monitor_state not in ("stopped", "lost"):
        blocked_reason = _continuation_dispatch_blocked_reason(meta)
        if blocked_reason and _repair_missing_starter_parent(artifacts_dir, meta):
            blocked_reason = _continuation_dispatch_blocked_reason(meta)
    if blocked_reason:
        followup_error = _blocked_followup_error(blocked_reason, meta)
        snapshot_worktree_recovery_diff(artifacts_dir, meta)
        meta[_MONITOR_SETTLEMENT_CONFIG.outcome_field] = "not-launchable"
        meta[_MONITOR_SETTLEMENT_CONFIG.error_field] = followup_error
        update_meta_field(
            artifacts_dir,
            _MONITOR_SETTLEMENT_CONFIG.outcome_field,
            "not-launchable",
        )
        update_meta_field(
            artifacts_dir,
            _MONITOR_SETTLEMENT_CONFIG.error_field,
            followup_error,
        )
        release_error = _release_monitor_claim(
            meta, project_name=project_name, artifacts_dir=artifacts_dir
        )
        return _MonitorFollowupSettlementResult(
            error=release_error or followup_error,
            launch_result=FollowupLaunchResult(
                launched=False,
                error=followup_error,
            ),
        )

    from sase.monitor.outcome_policy import (
        apply_frozen_branch,
        frozen_action,
        settlement_policy_decision,
        should_launch_frozen_followup,
    )

    decision = settlement_policy_decision(artifacts_dir, meta, monitor_state)
    if frozen_action(decision) == "complete":
        completion_ref = decision.get("completion_ref")
        if isinstance(completion_ref, str) and completion_ref.strip():
            meta.setdefault("monitor_completion_ref", completion_ref.strip())
        host_settlement = settle_host_completion(
            artifacts_dir,
            meta,
            monitor_state=monitor_state,
            exit_code=exit_code,
            elapsed_seconds=elapsed_seconds,
            project_name=project_name,
            launch_recovery=launch_and_capture,
            release_claim=_make_retention_release_claim(artifacts_dir),
            capture=capture,
            selected_action="complete",
            timeout_kind=timeout_kind,
            transfer_from_pid=transfer_from_pid,
        )
        if host_settlement is not None:
            if captured_launch_result is None:
                captured_launch_result = host_settlement.launch_result
            settlement_launch_result = captured_launch_result
            if (
                settlement_launch_result is not None
                and settlement_launch_result.host_completed
                and not meta.get(_MONITOR_SETTLEMENT_CONFIG.outcome_field)
            ):
                record_turn_followup_outcome(
                    artifacts_dir,
                    meta,
                    outcome=HOST_COMPLETED_OUTCOME,
                    config=_MONITOR_SETTLEMENT_CONFIG,
                    update_meta_field=update_meta_field,
                )
            elif captured_launch_result is not None and not meta.get(
                _MONITOR_SETTLEMENT_CONFIG.outcome_field
            ):
                if captured_launch_result.launched:
                    outcome = (
                        _MONITOR_SETTLEMENT_CONFIG.degraded_outcome
                        if captured_launch_result.degraded_reason
                        else "launched"
                    )
                else:
                    outcome = "not-launchable"
                record_turn_followup_outcome(
                    artifacts_dir,
                    meta,
                    outcome=outcome,
                    config=_MONITOR_SETTLEMENT_CONFIG,
                    update_meta_field=update_meta_field,
                    degraded_reason=captured_launch_result.degraded_reason,
                    prompt_path=captured_launch_result.prompt_path,
                )
            return _MonitorFollowupSettlementResult(
                error=host_settlement.error, launch_result=captured_launch_result
            )

    if should_launch_frozen_followup(decision, monitor_state):
        apply_frozen_branch(artifacts_dir, meta, decision)
    elif monitor_state not in ("stopped", "lost"):
        meta.pop(_MONITOR_SETTLEMENT_CONFIG.next_action_field, None)

    error = settle_turn_claim_and_followup(
        artifacts_dir,
        meta,
        shell_state=monitor_state,
        project_name=project_name,
        config=_MONITOR_SETTLEMENT_CONFIG,
        release_claim=_make_retention_release_claim(artifacts_dir),
        launch_followup=launch_and_capture,
        launch_kwargs={
            "monitor_state": monitor_state,
            "exit_code": exit_code,
            "elapsed_seconds": elapsed_seconds,
            "capture": capture,
            "timeout_kind": timeout_kind,
            "project_name": project_name,
            "transfer_from_pid": transfer_from_pid,
        },
        update_meta_field=update_meta_field,
    )
    return _MonitorFollowupSettlementResult(
        error=error, launch_result=captured_launch_result
    )


def _continuation_dispatch_blocked_reason(meta: dict[str, Any]) -> str | None:
    from sase.continuation_capture import continuation_dispatch_blocked_reason

    return continuation_dispatch_blocked_reason(meta)


def _repair_missing_starter_parent(artifacts_dir: str, meta: dict[str, Any]) -> bool:
    """Give a missing-starter-parent disposition one more chance to clear.

    The starter may settle in the gap between result-capture publish (which
    already waited, bounded, for it once) and this settlement call.
    """
    from sase.continuation_capture import repair_missing_starter_parent_disposition

    return repair_missing_starter_parent_disposition(artifacts_dir, meta)


def _blocked_followup_error(reason: str, meta: dict[str, Any]) -> str:
    from sase.continuation_capture import starter_capture_error_summary

    message = reason
    if reason == _missing_starter_parent_error():
        starter_dir = meta.get("monitor_starter_artifacts_dir")
        summary = starter_capture_error_summary(
            starter_dir if isinstance(starter_dir, str) else None
        )
        if summary:
            starter = meta.get("monitor_starter_agent")
            starter_name = (
                starter if isinstance(starter, str) and starter else "unknown"
            )
            message += (
                f"; starter {starter_name} continuation capture failed ({summary})"
            )

    monitor_id = meta.get("monitor_id")
    short_id = (
        short_monitor_id(monitor_id) if isinstance(monitor_id, str) else "unknown"
    )
    return (
        f"{message}; recover with `sase monitor resume {short_id} -k FILE` "
        f"or `sase monitor resume {short_id} -m MODEL`"
    )


def _missing_starter_parent_error() -> str:
    from sase.continuation_capture.monitor import _MISSING_STARTER_PARENT_ERROR

    return _MISSING_STARTER_PARENT_ERROR


def _coerce_monitor_followup_result(
    raw: bool | FollowupLaunchResult,
    meta: dict[str, Any],
) -> FollowupLaunchResult:
    """Coerce legacy boolean monitor follow-up launchers into a result."""
    if isinstance(raw, FollowupLaunchResult):
        return raw
    if raw:
        agent = meta.get(_MONITOR_SETTLEMENT_CONFIG.agent_field)
        return FollowupLaunchResult(
            launched=True,
            agent_name=agent if isinstance(agent, str) and agent else None,
        )
    error = meta.get(_MONITOR_SETTLEMENT_CONFIG.error_field)
    prompt_path = meta.get(_MONITOR_SETTLEMENT_CONFIG.prompt_path_field)
    return FollowupLaunchResult(
        launched=False,
        error=error if isinstance(error, str) and error else None,
        prompt_path=prompt_path
        if isinstance(prompt_path, str) and prompt_path
        else None,
    )


def _make_retention_release_claim(artifacts_dir: str) -> Any:
    """Return a ``ClaimReleaser`` that settles through the retention adapter."""

    def _release(
        meta: dict[str, Any],
        project_name: str | None,
    ) -> str | None:
        return _release_monitor_claim(
            meta, project_name=project_name, artifacts_dir=artifacts_dir
        )

    return _release


def _release_monitor_claim(
    meta: dict[str, Any],
    *,
    project_name: str | None,
    artifacts_dir: str,
) -> str | None:
    """Settle this monitor member's workspace claim through guarded retention.

    Routes every terminal monitor claim disposal — stopped/lost states,
    no-follow-up outcomes, launch failures, blocked continuation capture,
    frozen-policy branches, and degraded follow-ups — through
    :func:`sase.turns.workspace_retention.settle_stranded_workspace`. A
    confirmed same-workspace successor keeps custody (no hold); a degraded
    follow-up in another checkout retains the original dirty workspace; a
    missing or moved claim is a no-op. Returns ``None`` when settlement
    succeeded (retained, released, or stale); returns an error string only
    when the owner cannot be resolved and the legacy release fails, or when
    the adapter itself errors before applying an effect.
    """
    workspace_num = meta.get("workspace_num")
    if not project_name or not isinstance(workspace_num, int):
        return None
    try:
        from sase.workflows.utils import get_project_file_path

        project_file = get_project_file_path(project_name)
    except Exception:
        return None

    pid = meta.get("pid")
    if not isinstance(pid, int):
        return _legacy_release_monitor_claim(
            project_file, workspace_num, meta.get("cl_name")
        )

    owner = _build_retention_owner(
        artifacts_dir, meta, project_name, project_file, workspace_num, pid
    )
    if owner is None:
        return _legacy_release_monitor_claim(
            project_file, workspace_num, meta.get("cl_name")
        )
    successor = _retention_successor_from_meta(meta)
    try:
        from sase.turns.workspace_retention import settle_stranded_workspace

        result = settle_stranded_workspace(owner, successor=successor)
    except Exception as exc:  # noqa: BLE001 - never drop a claim on error
        return f"workspace retention settlement failed: {exc}"
    if result.disposition == "release" and not result.claim_changed:
        return result.reason or "workspace release failed"
    return None


def _legacy_release_monitor_claim(
    project_file: str,
    workspace_num: int,
    cl_name: object,
) -> str | None:
    """Release a pid-less monitor claim without ownership checks."""
    from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
    from sase.running_field import release_workspace

    result = release_workspace(
        project_file,
        workspace_num,
        MONITOR_WORKSPACE_CLAIM_WORKFLOW,
        cl_name=cl_name if isinstance(cl_name, str) else None,
    )
    if not result.success:
        return result.error or "workspace release failed"
    return None


def _build_retention_owner(
    artifacts_dir: str,
    meta: dict[str, Any],
    project_name: str,
    project_file: str,
    workspace_num: int,
    pid: int,
) -> Any | None:
    """Build a concrete retention owner from monitor metadata."""
    import os

    from sase.turns.workspace_retention import (
        WorkspaceRetentionOwner,
    )

    from .staged_owner import read_staged_owner_index

    cl_name = meta.get("cl_name")
    artifacts_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
    checkout_dir = _retention_checkout_dir(meta)
    repos = _discover_retention_repos(artifacts_dir, meta, checkout_dir)
    monitor_id = meta.get("monitor_id")
    staged_id = meta.get("monitor_staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        staged_id = None
        if isinstance(monitor_id, str) and monitor_id:
            try:
                staged = read_staged_owner_index(monitor_id)
            except Exception:  # noqa: BLE001 - staged index is best effort
                staged = None
            if isinstance(staged, dict):
                candidate = staged.get("staged_id")
                if isinstance(candidate, str) and candidate:
                    staged_id = candidate
    session_id = meta.get("agent_session")
    if not isinstance(session_id, str) or not session_id:
        session_id = None
    turn_id = monitor_id if isinstance(monitor_id, str) and monitor_id else None
    terminal_reason = meta.get("monitor_state")
    if not isinstance(terminal_reason, str) or not terminal_reason:
        terminal_reason = "terminal"
    try:
        return WorkspaceRetentionOwner(
            project_file=project_file,
            workspace_num=workspace_num,
            workflow=_monitor_claim_workflow(),
            cl_name=cl_name if isinstance(cl_name, str) else "",
            artifacts_timestamp=artifacts_timestamp,
            pid=pid,
            artifacts_dir=artifacts_dir,
            checkout_dir=checkout_dir,
            repos=repos,
            origin_repo_ids=(),
            staged_id=staged_id,
            session_id=session_id,
            turn_id=turn_id,
            terminal_reason=terminal_reason,
        )
    except Exception:  # noqa: BLE001 - malformed metadata falls back
        return None


def _monitor_claim_workflow() -> str:
    from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW

    return MONITOR_WORKSPACE_CLAIM_WORKFLOW


def _retention_checkout_dir(meta: dict[str, Any]) -> str | None:
    """Return the workspace checkout the settling monitor ran in.

    Only an existing git-backed directory can carry retainable worktree
    evidence; a missing checkout (reboot-lost records, removed lanes) or a
    plain non-repo directory contributes no dirt and must not turn into a
    probe failure. The adapter probes ``checkout_dir`` when no explicit
    repos survive discovery, so this gate decides release-vs-retain for
    repo-less monitors.
    """
    import os

    for key in ("workspace_dir", "monitor_cwd"):
        candidate = meta.get(key)
        if (
            isinstance(candidate, str)
            and candidate.strip()
            and os.path.isdir(candidate)
            and _retention_git_toplevel(candidate) is not None
        ):
            return candidate
    return None


def _discover_retention_repos(
    artifacts_dir: str,
    meta: dict[str, Any],
    checkout_dir: str | None,
) -> tuple[Any, ...]:
    """Collect relevant repositories for the settling monitor owner."""
    from sase.turns.workspace_retention import WorkspaceRetentionRepo

    ordered: list[str] = []
    seen: set[str] = set()

    def _add(path: object) -> None:
        if not isinstance(path, str) or not path.strip():
            return
        normalized = path.strip()
        if normalized in seen:
            return
        seen.add(normalized)
        ordered.append(normalized)

    _add(checkout_dir)
    _add(meta.get("monitor_cwd"))
    _add(meta.get("workspace_dir"))
    continuation_ref = meta.get("continuation_workspace_ref")
    _add(continuation_ref)
    for baseline_dir in (artifacts_dir, meta.get("monitor_starter_artifacts_dir")):
        if not isinstance(baseline_dir, str) or not baseline_dir.strip():
            continue
        try:
            from pathlib import Path

            from sase.llm_provider.commit_finalizer_baseline import (
                load_finalizer_baseline_records,
            )

            records = load_finalizer_baseline_records(Path(baseline_dir)) or ()
            for record in records:
                _add(getattr(record, "path", None))
        except Exception:  # noqa: BLE001 - baseline discovery is best effort
            continue
    repos: list[Any] = []
    for index, path in enumerate(ordered):
        import os

        if not os.path.isdir(path) or _retention_git_toplevel(path) is None:
            continue
        repos.append(
            WorkspaceRetentionRepo(
                repo_id="primary" if index == 0 else f"linked-{index}",
                path=path,
                is_primary=index == 0,
                positive_custody=True,
            )
        )
        if len(repos) >= 8:
            break
    return tuple(repos)


def _retention_git_toplevel(path: str) -> str | None:
    """Return the enclosing git work-tree root for *path*, if any.

    A directory outside any git repository cannot carry session-owned
    uncommitted work in the sense the retention policy protects, so it
    contributes no dirt evidence instead of a probe failure.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:  # noqa: BLE001 - evidence probes never block settlement
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def _retention_successor_from_meta(meta: dict[str, Any]) -> Any:
    """Derive successor custody from the recorded follow-up outcome."""
    from sase.turns.workspace_retention import WorkspaceRetentionSuccessor

    outcome = meta.get("monitor_followup_outcome")
    if outcome == MONITOR_FOLLOWUP_DEGRADED_OUTCOME:
        return WorkspaceRetentionSuccessor(
            confirmed_active=True,
            same_workspace=False,
            inherited_obligations=True,
        )
    if outcome == "launched":
        return WorkspaceRetentionSuccessor(
            confirmed_active=True,
            same_workspace=True,
            inherited_obligations=True,
        )
    return WorkspaceRetentionSuccessor()


def touch_monitor_refresh_pulse(project_name: str | None) -> None:
    """Nudge artifact watchers after monitor metadata changes."""
    touch_turn_refresh_pulse(project_name)


def finalize_monitor_workflow_state(artifacts_dir: str) -> None:
    """Rewrite a settled monitor member's workflow_state.json to terminal."""
    finalize_turn_workflow_state(artifacts_dir)


def project_name_from_artifacts_dir(artifacts_dir: str) -> str | None:
    """Return the project containing a monitor artifacts directory."""
    return shell_project_name_from_artifacts_dir(artifacts_dir)


__all__ = [
    "LOST_FOLLOWUP_ERROR",
    "finalize_monitor_workflow_state",
    "project_name_from_artifacts_dir",
    "settle_claim_and_followup",
    "touch_monitor_refresh_pulse",
]
