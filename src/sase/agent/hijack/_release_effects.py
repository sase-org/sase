"""Post-snapshot effects for snapshot-verified release resolutions.

The ledger reservation (``held|expired`` → ``resolving``) and the snapshot
gate already happened when these run: the workspace is still held, then each
effect releases it. A dismiss retires the row through the existing
ownership-checked dismiss and releases the bead claim, as a kill does. A
restart runs the existing restart planner and executor (same raw prompt,
same name, fresh workspace). A restart with a replacement prompt — the Edit
backend — dismisses first, then launches the given prompt through the normal
name-reuse path, so a changed ``%id`` works.

Failures before the workspace is released return the record to held; anything
after the release keeps ``resolving`` and reports uncertain, with the ledger's
prompt and snapshot refs left for manual recovery.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack._release_settle import (
    settle_release_dismiss,
    settle_release_restart,
)
from sase.agent.hijack.recover_common import (
    RESULT_ERROR,
    RESULT_LAUNCHED,
    RESULT_REFUSED,
    RESULT_UNCERTAIN,
    RecoveryRefusal,
    RecoveryResult,
    clean_string,
    code_detail,
    fail_to_held,
    record_revision,
    reload_record,
)

LOG = logging.getLogger(__name__)


@dataclass
class ReleaseEffectDeps:
    """Injectable seams for release effects; defaults perform real I/O."""

    dismiss_row: Callable[..., Any] | None = None
    plan_restart: Callable[..., Any] | None = None
    execute_restart: Callable[..., Any] | None = None
    plan_replacement_reuse: Callable[..., Any] | None = None
    apply_replacement_reuse: Callable[..., Any] | None = None
    launch_replacement: Callable[..., Any] | None = None
    release_bead_claim: Callable[[Mapping[str, Any]], tuple[bool, str]] | None = None


def dismiss_resolved(
    resolving: Mapping[str, Any],
    *,
    deps: ReleaseEffectDeps | None = None,
) -> RecoveryResult:
    """Dismiss the held row, release its bead claim, and settle dismissed."""
    seams = deps or ReleaseEffectDeps()
    record = dict(resolving)
    hijack_id = clean_string(record.get("hijack_id"))
    agent_name = clean_string(record.get("agent_name")) or ""
    dismiss_row = seams.dismiss_row or _default_dismiss_row
    try:
        dismissed = dismiss_row(agent_name)
    except Exception as exc:  # noqa: BLE001 - dismiss boundary reports errors
        return RecoveryResult(
            kind=RESULT_ERROR,
            hijack_id=hijack_id,
            revision=record_revision(reload_record(hijack_id or "", record)),
            action="dismiss",
            message=f"Could not dismiss hijacked agent {agent_name!r}: {exc}",
            detail={**code_detail("dismiss_failed"), "agent_name": agent_name},
        )
    if not getattr(dismissed, "success", False):
        reason = str(getattr(dismissed, "reason", "") or "")
        if reason == "not_found":
            LOG.warning(
                "hijack dismiss: row %r already gone; settling anyway", agent_name
            )
        else:
            fail_to_held(record, str(getattr(dismissed, "message", "") or reason))
            current = reload_record(hijack_id or "", record)
            return RecoveryResult(
                kind=RESULT_ERROR,
                hijack_id=hijack_id,
                revision=record_revision(current),
                action="dismiss",
                message=str(
                    getattr(dismissed, "message", "")
                    or f"Could not dismiss hijacked agent {agent_name!r}"
                ),
                detail={**code_detail(reason or "dismiss_failed")},
            )
    _release_held_bead_claim(record, release_fn=seams.release_bead_claim)
    try:
        settled = settle_release_dismiss(record)
    except RecoveryRefusal as exc:
        current = reload_record(hijack_id or "", record)
        return RecoveryResult(
            kind=RESULT_UNCERTAIN,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action="dismiss",
            message=exc.message,
            detail={**code_detail(exc.code), "launch_stage": "settling"},
        )
    return RecoveryResult(
        kind=RESULT_LAUNCHED,
        hijack_id=hijack_id,
        revision=record_revision(settled),
        action="dismiss",
        message=(
            f"Dismissed hijacked agent {agent_name!r}; its workspace was released"
        ),
        detail={**code_detail("dismissed"), "agent_name": agent_name},
    )


def restart_resolved(
    resolving: Mapping[str, Any],
    *,
    replacement_prompt: str | None = None,
    deps: ReleaseEffectDeps | None = None,
) -> RecoveryResult:
    """Restart the hijacked agent and settle the record resolved."""
    seams = deps or ReleaseEffectDeps()
    record = dict(resolving)
    hijack_id = clean_string(record.get("hijack_id"))
    agent_name = clean_string(record.get("agent_name")) or ""
    if replacement_prompt is not None:
        return _restart_with_replacement(
            record,
            hijack_id=hijack_id,
            agent_name=agent_name,
            replacement_prompt=replacement_prompt,
            seams=seams,
        )
    plan_restart = seams.plan_restart or _default_plan_restart
    try:
        plan = plan_restart(agent_name)
    except Exception as exc:
        reason = getattr(exc, "reason", None)
        fail_to_held(record, str(exc))
        current = reload_record(hijack_id or "", record)
        return RecoveryResult(
            kind=RESULT_REFUSED
            if reason in {"fanout", "multi_segment", "container"}
            else RESULT_ERROR,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action="restart",
            message=str(exc),
            detail={**code_detail(str(reason) if reason else "restart_unavailable")},
        )
    execute_restart = seams.execute_restart or _default_execute_restart
    try:
        outcome = execute_restart(plan)
    except Exception as exc:  # noqa: BLE001 - executor boundary reports errors
        return _uncertain_after_release(
            record, hijack_id, action="restart", message=f"Restart failed: {exc}"
        )
    status = str(getattr(outcome, "status", "") or "")
    if status == "ok":
        successor = (
            clean_string(getattr(outcome, "renamed_to", None))
            or plan.name
            or agent_name
        )
        try:
            settled = settle_release_restart(record, successor=successor)
        except RecoveryRefusal as exc:
            return _uncertain_after_release(
                record, hijack_id, action="restart", message=exc.message
            )
        return RecoveryResult(
            kind=RESULT_LAUNCHED,
            hijack_id=hijack_id,
            revision=record_revision(settled),
            action="restart",
            successor=successor,
            message=(
                f"Restarted hijacked agent {agent_name!r} as {successor!r} in a "
                "fresh workspace"
            ),
            detail={
                **code_detail("restarted"),
                "agent_name": agent_name,
                "recovery_command": getattr(outcome, "recovery_command", None),
            },
        )
    if status == "kill_failed":
        fail_to_held(record, str(getattr(outcome, "error", "") or status))
        current = reload_record(hijack_id or "", record)
        return RecoveryResult(
            kind=RESULT_ERROR,
            hijack_id=hijack_id,
            revision=record_revision(current),
            action="restart",
            message=str(
                getattr(outcome, "error", "")
                or f"Could not stop hijacked agent {agent_name!r} for restart"
            ),
            detail={**code_detail("restart_stop_failed"), "status": status},
        )
    return _uncertain_after_release(
        record,
        hijack_id,
        action="restart",
        message=str(
            getattr(outcome, "error", "")
            or f"Restart stopped {agent_name!r} but the relaunch failed"
        ),
        recovery_command=getattr(outcome, "recovery_command", None),
    )


def _restart_with_replacement(
    record: dict[str, Any],
    *,
    hijack_id: str | None,
    agent_name: str,
    replacement_prompt: str,
    seams: ReleaseEffectDeps,
) -> RecoveryResult:
    """Dismiss the held row, then launch the replacement prompt normally."""
    dismiss_row = seams.dismiss_row or _default_dismiss_row
    try:
        dismissed = dismiss_row(agent_name)
    except Exception as exc:  # noqa: BLE001 - dismiss boundary reports errors
        return _uncertain_after_release(
            record,
            hijack_id,
            action="restart",
            message=f"Could not dismiss hijacked agent {agent_name!r} for edit: {exc}",
        )
    if not getattr(dismissed, "success", False):
        reason = str(getattr(dismissed, "reason", "") or "")
        if reason != "not_found":
            fail_to_held(record, str(getattr(dismissed, "message", "") or reason))
            current = reload_record(hijack_id or "", record)
            return RecoveryResult(
                kind=RESULT_ERROR,
                hijack_id=hijack_id,
                revision=record_revision(current),
                action="restart",
                message=str(
                    getattr(dismissed, "message", "")
                    or f"Could not dismiss hijacked agent {agent_name!r} for edit"
                ),
                detail={**code_detail(reason or "dismiss_failed")},
            )
    _release_held_bead_claim(record, release_fn=seams.release_bead_claim)
    plan_reuse = seams.plan_replacement_reuse or _default_plan_replacement_reuse
    try:
        reuse_plan = plan_reuse(replacement_prompt)
    except Exception as exc:
        return _uncertain_after_release(
            record,
            hijack_id,
            action="restart",
            message=f"Edited prompt cannot be relaunched: {exc}",
        )
    if reuse_plan is None:
        return _uncertain_after_release(
            record,
            hijack_id,
            action="restart",
            message="Edited prompt has no single agent to relaunch under one name",
        )
    apply_reuse = seams.apply_replacement_reuse or _default_apply_replacement_reuse
    try:
        apply_reuse(reuse_plan)
    except Exception as exc:
        return _uncertain_after_release(
            record,
            hijack_id,
            action="restart",
            message=f"Edited prompt name reuse failed: {exc}",
        )
    launch = seams.launch_replacement or _default_launch_replacement
    try:
        launched_name = launch(reuse_plan)
    except Exception as exc:
        return _uncertain_after_release(
            record,
            hijack_id,
            action="restart",
            message=f"Edited prompt launch failed: {exc}",
        )
    try:
        settled = settle_release_restart(record, successor=launched_name)
    except RecoveryRefusal as exc:
        return _uncertain_after_release(
            record, hijack_id, action="restart", message=exc.message
        )
    current = reload_record(hijack_id or "", settled)
    return RecoveryResult(
        kind=RESULT_LAUNCHED,
        hijack_id=hijack_id,
        revision=record_revision(current),
        action="restart",
        successor=launched_name,
        message=(f"Relaunched edited prompt as {launched_name!r} in a fresh workspace"),
        detail={**code_detail("restarted"), "agent_name": agent_name},
    )


def _uncertain_after_release(
    record: Mapping[str, Any],
    hijack_id: str | None,
    *,
    action: str,
    message: str,
    recovery_command: Any = None,
) -> RecoveryResult:
    """Report a post-release failure that keeps ``resolving`` for recovery."""
    current = reload_record(hijack_id or "", record)
    try:
        snapshots = list(current.get("snapshots") or [])
    except Exception:  # noqa: BLE001 - evidence is best effort
        snapshots = []
    detail: dict[str, Any] = {**code_detail("release_uncertain")}
    if recovery_command:
        detail["recovery_command"] = recovery_command
    if snapshots:
        detail["snapshots"] = snapshots
    return RecoveryResult(
        kind=RESULT_UNCERTAIN,
        hijack_id=hijack_id,
        revision=record_revision(current),
        action=action,
        message=message,
        detail=detail,
    )


def _default_dismiss_row(name: str) -> Any:
    from sase.agent.running import dismiss_named_agent

    return dismiss_named_agent(name, exact_name=True)


def _default_plan_restart(name: str) -> Any:
    from sase.agent._restart_planning import plan_agent_restart

    return plan_agent_restart(name)


def _default_execute_restart(plan: Any) -> Any:
    from sase.agent._restart_execute import execute_agent_restart

    return execute_agent_restart(plan)


def _default_plan_replacement_reuse(prompt: str) -> Any:
    from sase.agent.force_reuse_launch import plan_force_reuse_launch

    return plan_force_reuse_launch(prompt)


def _default_apply_replacement_reuse(reuse_plan: Any) -> None:
    from sase.agent.force_reuse_launch import apply_force_reuse_launch

    apply_force_reuse_launch(reuse_plan)


def _default_launch_replacement(reuse_plan: Any) -> str | None:
    """Launch the replacement prompt from home and return its agent name."""

    from sase.agent.launch_cwd import launch_agents_from_cwd
    from sase.env_contracts import SASE_LAUNCH_SUBMITTED_AT_ENV

    segment_envs = getattr(reuse_plan, "segment_envs", None)
    rewritten = getattr(reuse_plan, "rewritten_prompt", "")
    restart_segment_envs: list[Any] | None = None
    if isinstance(segment_envs, list):
        restart_segment_envs = [
            None
            if env is None
            else {
                key: value
                for key, value in env.items()
                if key != SASE_LAUNCH_SUBMITTED_AT_ENV
            }
            for env in segment_envs
        ]
    with contextlib.chdir(Path.home()):
        results = launch_agents_from_cwd(
            rewritten,
            segment_extra_env=restart_segment_envs,
            origin="generated",
        )
    if not results:
        raise RuntimeError("agent launch produced no results")
    launched = results[0]
    return clean_string(getattr(launched, "agent_name", None))


def _release_held_bead_claim(
    record: Mapping[str, Any],
    *,
    release_fn: Callable[[Mapping[str, Any]], tuple[bool, str]] | None = None,
) -> None:
    """Release the predecessor's bead claim, as a kill does.

    Best effort: staged handoffs and promoted bead claims keep theirs, and a
    release failure only warns, because the workspace release already settled
    custody of the work.
    """
    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return
    if _staged_handoff_keeps_claim(artifacts_dir):
        LOG.info("release keeps bead claim: staged handoff owns it")
        return
    if _promoted_bead_claim(artifacts_dir):
        LOG.info("release keeps bead claim: agent_meta promoted it")
        return
    release = release_fn or _default_release_bead_claim
    try:
        released, message = release(record)
    except Exception as exc:  # noqa: BLE001 - bead release stays best effort
        LOG.warning("release bead claim failed: %s", exc)
        return
    if not released:
        LOG.warning("release bead claim skipped: %s", message)


def _staged_handoff_keeps_claim(artifacts_dir: str) -> bool:
    try:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            read_adoption_receipt,
            read_staged_handoff,
        )
    except Exception:  # noqa: BLE001 - guard fails open to releasing
        return False
    try:
        if read_staged_handoff(artifacts_dir) is not None:
            return True
    except StagedHandoffError:
        return True
    except Exception:  # noqa: BLE001 - guard fails open to keeping
        return True
    try:
        return read_adoption_receipt(artifacts_dir) is not None
    except StagedHandoffError:
        return True
    except Exception:  # noqa: BLE001 - guard fails open to keeping
        return True


def _promoted_bead_claim(artifacts_dir: str) -> bool:
    import json
    import os

    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as stream:
            payload = json.load(stream)
    except (FileNotFoundError, ValueError, OSError):
        return False
    return isinstance(payload, dict) and payload.get("bead_claim_promoted") is True


def _default_release_bead_claim(record: Mapping[str, Any]) -> tuple[bool, str]:
    """Release the predecessor's store-side bead claim and clear its marker."""
    import sys

    from sase.bead.claims import (
        BeadClaimReleaseOutcome,
        clear_bead_claim_marker,
        read_bead_claim_marker,
        release_bead_claim_for_agent,
    )

    artifacts_dir = clean_string(record.get("artifacts_dir")) or ""
    marker = read_bead_claim_marker(artifacts_dir) if artifacts_dir else None
    if marker is None:
        return False, "no bead claim marker on the predecessor"
    outcome = BeadClaimReleaseOutcome.ERROR
    try:
        outcome = release_bead_claim_for_agent(
            project_name=marker.project_name,
            bead_id=marker.bead_id,
            agent_name=marker.agent_name,
        )
    except Exception as exc:  # noqa: BLE001 - reported through the outcome
        print(
            f"Warning: Failed to release bead claim on '{marker.bead_id}' from "
            f"agent '{marker.agent_name}': {exc}",
            file=sys.stderr,
        )
        return False, str(exc)
    if outcome is not BeadClaimReleaseOutcome.ERROR and artifacts_dir:
        clear_bead_claim_marker(artifacts_dir)
    if outcome is BeadClaimReleaseOutcome.RELEASED:
        return True, f"released bead claim on {marker.bead_id}"
    return False, f"bead claim release outcome: {outcome.value}"


__all__ = [
    "ReleaseEffectDeps",
    "dismiss_resolved",
    "restart_resolved",
]
