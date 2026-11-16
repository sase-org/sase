"""Replay an already-adopted staged handoff into the live runner."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.staged_handoff import StagedHandoffError, read_staged_successor
from sase.axe._run_agent_exec_staged_shared import (
    StagedHandoffDispatch,
    StagedInlineContinuation,
)


def already_adopted_dispatch(
    receipt: Mapping[str, Any],
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    continuation: StagedInlineContinuation,
) -> StagedHandoffDispatch:
    try:
        from sase.agent.hijack.runner_boundaries import (
            enforce_adoption_replay_latch as _enforce_already_replay,
        )

        _enforce_already_replay(artifacts_dir)
    except Exception as already_exc:
        from sase.agent.hijack.spawn_guard import HijackLatchedError as _AlreadyLatched

        if isinstance(already_exc, _AlreadyLatched):
            raise
    receipt_refs = receipt.get("refs")
    receipt_refs = receipt_refs if isinstance(receipt_refs, Mapping) else {}
    outcome = receipt_refs.get("loop_outcome")
    if outcome is not None and not isinstance(outcome, str):
        raise StagedHandoffError("staged adoption receipt has an invalid loop outcome")
    if "loop_outcome" not in receipt_refs:
        outcome = "completed"
    if staged_record.get("kind") in {"pipe", "plan", "questions"} and outcome is None:
        staged_id = str(staged_record.get("staged_id") or "")
        successor = read_staged_successor(artifacts_dir, staged_id=staged_id)
        if successor is None:
            if receipt_refs.get("successor_artifacts_dir") is not None:
                return StagedHandoffDispatch(
                    adopted=False,
                    reason=(
                        "adopted inline receipt references a missing successor identity"
                    ),
                    already_adopted=True,
                )
            return StagedHandoffDispatch(
                adopted=True,
                outcome=outcome,
                already_adopted=True,
            )
        successor_dir = str(successor["successor"]["artifacts_dir"])
        if receipt_refs.get("successor_artifacts_dir") != successor_dir:
            return StagedHandoffDispatch(
                adopted=False,
                reason=(
                    "adopted inline receipt does not match the persisted successor"
                ),
                already_adopted=True,
            )
        launch_identity = receipt_refs.get("successor_launch_identity")
        if (
            launch_identity is not None
            and launch_identity != successor["successor"]["launch_identity"]
        ):
            return StagedHandoffDispatch(
                adopted=False,
                reason="adopted inline receipt has a mismatched launch identity",
                already_adopted=True,
            )
        if successor["delivery_state"] in {"submitted", "started", "terminal"}:
            return StagedHandoffDispatch(
                adopted=True,
                outcome="completed",
                already_adopted=True,
            )
        try:
            if staged_record.get("kind") == "pipe":
                from sase.axe.run_agent_exec_pipe import restore_staged_pipe_successor

                restore_staged_pipe_successor(continuation.state, successor)
            else:
                from sase.axe.run_agent_successor import (
                    restore_staged_successor_in_loop,
                )

                restore_staged_successor_in_loop(continuation.state, successor)
        except Exception as exc:  # noqa: BLE001 - refuse malformed replay state.
            return StagedHandoffDispatch(
                adopted=False,
                reason=f"adopted inline successor cannot be restored: {exc}",
                already_adopted=True,
            )
    return StagedHandoffDispatch(
        adopted=True,
        outcome=outcome,
        already_adopted=True,
    )


__all__ = ["already_adopted_dispatch"]
