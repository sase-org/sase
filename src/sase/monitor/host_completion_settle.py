"""Prepared-intent entry point for no-model host completion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sase.core.continuation_facade import resolve_continuation_policy
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.prepare import load_prepared_completion
from sase.monitor._host_completion_shared import (
    DEFAULT_RECOVERY_ACTION,
    HostCompletionSettlement,
)
from sase.monitor.host_completion_run import run_host_completion
from sase.monitor.host_completion_state import intent_artifacts_dir
from sase.monitor.output import OutputCapture
from sase.turns.followup import FollowupLaunchResult


def settle_host_completion(
    artifacts_dir: str,
    meta: dict[str, Any],
    *,
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float,
    project_name: str | None,
    launch_recovery: Callable[..., FollowupLaunchResult],
    release_claim: Callable[[dict[str, Any], str | None], str | None],
    capture: OutputCapture,
    selected_action: str | None = None,
    timeout_kind: str | None = None,
    transfer_from_pid: int | None = None,
) -> HostCompletionSettlement | None:
    """Attempt host completion when a prepared intent is bound.

    Returns ``None`` when the resolved policy is not ``complete`` so the
    caller can fall through to ordinary follow-up launch.
    """

    completion_ref = str(meta.get("monitor_completion_ref") or "") or str(
        meta.get("continuation_completion_ref") or ""
    )
    if not completion_ref:
        return None
    if selected_action != "complete":
        policy = resolve_continuation_policy(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "outcome": _policy_outcome_name(monitor_state),
                "profile": meta.get("monitor_profile") or None,
                "shared_next": meta.get("monitor_next_action") or None,
                "prepared_completion_ref": completion_ref,
                "prepared_completion_accept": _sealed_accept_for_resolve(
                    artifacts_dir, meta, completion_ref, project_name
                ),
            }
        )
        if policy.get("action") != "complete":
            return None
    if not str(meta.get("monitor_next_action") or "").strip():
        meta["monitor_next_action"] = DEFAULT_RECOVERY_ACTION
        from sase.axe.run_agent_helpers_artifacts import update_meta_field

        update_meta_field(artifacts_dir, "monitor_next_action", DEFAULT_RECOVERY_ACTION)
    return run_host_completion(
        artifacts_dir,
        meta,
        monitor_state=monitor_state,
        exit_code=exit_code,
        elapsed_seconds=elapsed_seconds,
        project_name=project_name,
        completion_ref=completion_ref,
        launch_recovery=launch_recovery,
        release_claim=release_claim,
        capture=capture,
        timeout_kind=timeout_kind,
        transfer_from_pid=transfer_from_pid,
    )


def _policy_outcome_name(monitor_state: str) -> str:
    from sase.monitor.host_completion_state import policy_outcome

    return policy_outcome(monitor_state)


def _sealed_accept_for_resolve(
    artifacts_dir: str,
    meta: Mapping[str, Any],
    completion_ref: str,
    project_name: str | None,
) -> str | None:
    """Return the sealed accept policy for a fallback policy resolution.

    Best effort: when the prepared intent cannot be read, return ``None``
    and resolution falls back to the default pass behavior.
    """

    try:
        intent = load_prepared_completion(
            completion_ref,
            artifacts_dir=intent_artifacts_dir(artifacts_dir, meta, project_name),
        )
    except Exception:  # noqa: BLE001 - resolution must fail open to pass.
        return None
    accept = intent.get("accept", "pass")
    if accept not in ("pass", "no_new_failures"):
        return None
    return str(accept)


__all__ = [
    "settle_host_completion",
]
