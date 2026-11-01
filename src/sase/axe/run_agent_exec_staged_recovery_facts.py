"""Persisted-fact observers for staged-handoff host recovery."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import StagedHandoffError, read_staged_successor
from sase.axe._run_agent_exec_staged_recovery_shared import SUCCESSOR_KINDS
from sase.axe.run_agent_exec_staged_settlement import finalizer_settlement_refusal


def observe_runner(run_metadata: Mapping[str, Any]) -> str:
    """Return the Rust runner wire state for persisted process evidence."""
    pid = run_metadata.get("pid")
    if type(pid) is not int or pid <= 0:
        return "unknown"
    identity = run_metadata.get("process_identity")
    try:
        from sase.agent.process_tree import process_is_running
        from sase.core.process_identity import process_identity_matches
    except Exception:  # noqa: BLE001 - unreadable platform helpers are unknown.
        return "unknown"
    try:
        if not process_is_running(pid):
            return "dead"
        if process_identity_matches(pid, identity):
            return "alive"
    except Exception:  # noqa: BLE001 - probing must not fail recovery.
        return "unknown"
    return "unknown"


def was_killed_or_discarded(
    artifacts_dir: str, run_metadata: Mapping[str, Any]
) -> bool:
    if run_metadata.get("handoff_protocol") == "killed":
        return True
    try:
        from sase.agent._user_kill_intent import has_user_kill_intent
    except Exception:  # noqa: BLE001 - missing helper is not kill evidence.
        return False
    try:
        return bool(has_user_kill_intent(artifacts_dir))
    except Exception:  # noqa: BLE001 - unreadable marker is not kill evidence.
        return False


def observe_settlement(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Return ``(wire_state, refusal)`` for finalizer settlement proof."""
    root = Path(artifacts_dir)
    if not (root / "finalizer_result.json").is_file():
        return "missing", "finalizer result is missing for this stage"
    try:
        refusal = finalizer_settlement_refusal(
            staged_record, artifacts_dir=artifacts_dir, run_metadata=run_metadata
        )
    except StagedHandoffError as exc:
        return "missing", f"finalizer settlement evidence is unreadable: {exc}"
    except Exception as exc:  # noqa: BLE001 - malformed proof holds adoption.
        return "missing", f"finalizer settlement evidence is unreadable: {exc}"
    if refusal is None:
        return "settled", None
    if "missing" in refusal or "absent" in refusal or "unreadable" in refusal:
        return "missing", refusal
    return "held", refusal


def observe_destination(staged_record: Mapping[str, Any], *, artifacts_dir: str) -> str:
    """Return the Rust destination wire state for durable effects."""
    kind = staged_record.get("kind")
    if kind not in SUCCESSOR_KINDS:
        return "absent"
    staged_id = staged_record.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return "absent"
    try:
        successor = read_staged_successor(artifacts_dir, staged_id=staged_id)
    except StagedHandoffError:
        return "absent"
    except Exception:  # noqa: BLE001 - unreadable successor is not an effect.
        return "absent"
    if successor is None:
        return "absent"
    state = str(successor.get("delivery_state") or "")
    if state == "terminal":
        return "terminal"
    if state in {"submitted", "started", "created", "prepared", "owned"}:
        return "pending" if state != "owned" else "owned"
    return "pending"


def repair_action_for(
    *,
    settlement: str,
    settlement_reason: str | None,
    runner: str,
    mode: str,
    kind: str | None,
    destination: str,
) -> str | None:
    if settlement in {"missing", "held"} and settlement_reason:
        lowered = settlement_reason.lower()
        if "declaration" in lowered or "submission" in lowered:
            return "complete the accepted final declaration, then re-run recovery"
        if "commit" in lowered or "repository" in lowered or "repo" in lowered:
            return "repair the unfinished commit finalizer work, then re-run recovery"
        if "carry" in lowered or "prepared" in lowered or "deferral" in lowered:
            return "retain carry/prepared proof and settle the remaining work first"
        if "provider response" in lowered or "ordinary provider" in lowered:
            return "recovery requires the persisted provider response"
        if "workspace" in lowered:
            return "reconcile workspace ownership before re-running recovery"
        return "settle the remaining finalizer obligations, then re-run recovery"
    if runner == "alive" and mode == "automatic":
        return "wait for the live runner or re-run recovery explicitly after it dies"
    if runner == "unknown":
        return "prove the originating runner is dead, then re-run recovery"
    if destination == "pending" and kind in SUCCESSOR_KINDS:
        return "re-run recovery to deliver the recorded successor exactly once"
    return None


def workspace_mismatch(
    run_metadata: Mapping[str, Any], recovery_context: Mapping[str, Any]
) -> str | None:
    expected = recovery_context.get("workspace_dir")
    observed = run_metadata.get("workspace_dir")
    if (
        isinstance(expected, str)
        and expected.strip()
        and isinstance(observed, str)
        and observed.strip()
        and Path(expected).resolve(strict=False) != Path(observed).resolve(strict=False)
    ):
        return "persisted workspace ownership changed since the stage was recorded"
    return None


__all__ = [
    "observe_destination",
    "observe_runner",
    "observe_settlement",
    "repair_action_for",
    "was_killed_or_discarded",
    "workspace_mismatch",
]
