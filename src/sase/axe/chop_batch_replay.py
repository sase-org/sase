"""Direct replay adapter for persisted ordinary chop launch batches."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import chop_batch_store


@dataclass(frozen=True)
class ChopBatchReplayResult:
    """Progress returned after reconciling and replaying one ordinary batch."""

    batch_id: str
    launched: tuple[Any, ...]
    already_launched: tuple[int, ...]
    blocked: tuple[dict[str, Any], ...]
    paused: bool = False


class ChopBatchReplayError(chop_batch_store.ChopBatchError):
    """Raised when a batch cannot be safely replayed through this adapter."""


def replay_ordinary_chop_batch(
    routine: str,
    job: str,
    batch_id: str,
    *,
    observations: Sequence[dict[str, Any]],
    observations_are_complete: bool,
    dispatch_member: Callable[..., Any],
    pause_requested_fn: Callable[[], bool] | None = None,
) -> ChopBatchReplayResult:
    """Replay only members the Rust reconciler identifies as safe to launch.

    ``observations`` is the complete result of inspecting durable spawn evidence,
    reservations, and live owners for this batch. An absent observation means the
    caller proved that no name reservation or spawn evidence exists. The callback
    receives the frozen member, including its exact name and prompt, plus
    ``before_spawn(request)`` and ``on_spawn_recorded(record)`` hooks. Launch
    adapters must invoke those hooks at the corresponding spawn boundaries.
    """
    if not observations_are_complete:
        raise ChopBatchReplayError(
            "ordinary batch replay requires a complete spawn observation snapshot"
        )

    if not chop_batch_store.acquire_chop_batch_ownership(
        routine, job, batch_id, owner="ordinary-replay"
    ):
        raise ChopBatchReplayError(f"batch {batch_id!r} already has a live owner")

    try:
        manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
        if manifest.get("typed_bundle") is not None:
            raise ChopBatchReplayError(
                "typed admission batches must be replayed by the typed adapter"
            )
        if manifest.get("status") == "paused":
            chop_batch_store.apply_chop_batch_event(routine, job, batch_id, "resume")
            manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)

        reconciliation = chop_batch_store.reconcile_stored_batch(
            routine, job, batch_id, [dict(item) for item in observations]
        )

        # A matched spawn can be ahead of its acknowledgement if the process
        # stopped in the spawn/ack window. Fold that durable evidence into the
        # journal before considering any new dispatch.
        for member_index in reconciliation["already_launched"]:
            member = manifest["members"][member_index]
            if member["status"] == "pending":
                chop_batch_store.apply_chop_batch_event(
                    routine,
                    job,
                    batch_id,
                    "begin_dispatch",
                    member_index=member_index,
                )
                chop_batch_store.apply_chop_batch_event(
                    routine,
                    job,
                    batch_id,
                    "acknowledge_launch",
                    member_index=member_index,
                )
            elif member["status"] == "dispatching":
                chop_batch_store.apply_chop_batch_event(
                    routine,
                    job,
                    batch_id,
                    "acknowledge_launch",
                    member_index=member_index,
                )

        launched: list[Any] = []
        paused = False

        def request_pause(reason: str) -> bool:
            try:
                chop_batch_store.apply_chop_batch_event(
                    routine,
                    job,
                    batch_id,
                    "request_pause",
                    reason=reason,
                )
            except chop_batch_store.ChopBatchError:
                if _batch_is_cancelled(routine, job, batch_id):
                    return False
                raise
            return True

        for member_index in reconciliation["to_launch"]:
            # Clan cancellation is persisted independently of the executor
            # owner, so it can arrive while one launcher call is in flight.
            # The begin_dispatch transition below is the atomic boundary: if
            # cancellation won first, it refuses the spawn; if dispatch won
            # first, that one launch may settle, but the next loop iteration
            # observes cancellation before it can start another member.
            if _batch_is_cancelled(routine, job, batch_id):
                break
            if pause_requested_fn is not None and pause_requested_fn():
                if _batch_is_cancelled(routine, job, batch_id):
                    break
                paused = request_pause(
                    "cooperative stop requested during ordinary replay"
                )
                break

            member = manifest["members"][member_index]
            boundary = {"started": False, "acknowledged": False}

            def before_spawn(
                request: Any,
                *,
                expected_name: str = str(member["agent_name"]),
                index: int = int(member_index),
                boundary_state: dict[str, bool] = boundary,
            ) -> None:
                if boundary_state["started"]:
                    raise ChopBatchReplayError(
                        f"member {index} reported more than one spawn boundary"
                    )
                actual_name = _request_agent_name(request)
                if actual_name != expected_name:
                    raise ChopBatchReplayError(
                        "replay request changed the accepted agent name: "
                        f"{actual_name!r} != {expected_name!r}"
                    )
                chop_batch_store.apply_chop_batch_event(
                    routine,
                    job,
                    batch_id,
                    "begin_dispatch",
                    member_index=index,
                )
                boundary_state["started"] = True

            def on_spawn_recorded(
                record: Any,
                *,
                expected_name: str = str(member["agent_name"]),
                index: int = int(member_index),
                boundary_state: dict[str, bool] = boundary,
                launched_records: list[Any] = launched,
            ) -> None:
                if not boundary_state["started"]:
                    raise ChopBatchReplayError(
                        f"member {index} was recorded before its spawn boundary"
                    )
                if boundary_state["acknowledged"]:
                    raise ChopBatchReplayError(
                        f"member {index} reported more than one spawn result"
                    )
                actual_name = _record_agent_name(record)
                if actual_name != expected_name:
                    raise ChopBatchReplayError(
                        "replay result changed the accepted agent name: "
                        f"{actual_name!r} != {expected_name!r}"
                    )
                chop_batch_store.apply_chop_batch_event(
                    routine,
                    job,
                    batch_id,
                    "acknowledge_launch",
                    member_index=index,
                )
                boundary_state["acknowledged"] = True
                launched_records.append(record)

            try:
                result = dispatch_member(
                    dict(member),
                    before_spawn=before_spawn,
                    on_spawn_recorded=on_spawn_recorded,
                )
            except ChopBatchReplayError:
                raise
            except chop_batch_store.ChopBatchError:
                if _batch_is_cancelled(routine, job, batch_id):
                    break
                raise
            if _batch_is_cancelled(routine, job, batch_id):
                break
            if boundary["started"] and not boundary["acknowledged"]:
                # Preserve the process-stop uncertainty window for the next
                # reconciliation. A synchronous successful return is durable
                # launch evidence even when an adapter lost its callback.
                on_spawn_recorded(result)
            elif not boundary["started"] and pause_requested_fn is not None:
                if pause_requested_fn():
                    paused = request_pause(
                        "cooperative stop requested during ordinary replay"
                    )
                    break
                raise ChopBatchReplayError(
                    f"replay adapter did not report the spawn boundary for member {member_index}"
                )
            elif not boundary["started"]:
                raise ChopBatchReplayError(
                    f"replay adapter did not report the spawn boundary for member {member_index}"
                )

            if pause_requested_fn is not None and pause_requested_fn():
                # The current member has been acknowledged; do not start the
                # next member after a stop request.
                if member_index != reconciliation["to_launch"][-1]:
                    paused = request_pause(
                        "cooperative stop requested during ordinary replay"
                    )
                    break

        refreshed = chop_batch_store.load_chop_batch(routine, job, batch_id)
        held = tuple(dict(item) for item in reconciliation["blocked"])
        return ChopBatchReplayResult(
            batch_id=batch_id,
            launched=tuple(launched),
            already_launched=tuple(reconciliation["already_launched"]),
            blocked=held,
            paused=paused or refreshed.get("status") == "paused",
        )
    finally:
        chop_batch_store.release_chop_batch_ownership(routine, job, batch_id)


def _request_agent_name(request: Any) -> str:
    evidence = getattr(request, "name_reservation", None)
    name = getattr(evidence, "agent_name", None)
    if name:
        return str(name)
    env = getattr(request, "extra_env", None) or {}
    return str(env.get("SASE_AGENT_PLANNED_NAME") or "")


def _record_agent_name(record: Any) -> str:
    result = getattr(record, "result", None)
    if result is not None:
        record = result
    return str(getattr(record, "agent_name", "") or "")


def _batch_is_cancelled(routine: str, job: str, batch_id: str) -> bool:
    """Return whether durable cancellation has won for this batch."""
    try:
        return (
            chop_batch_store.load_chop_batch(routine, job, batch_id).get("status")
            == "cancelled"
        )
    except chop_batch_store.ChopBatchError:
        return False


__all__ = [
    "ChopBatchReplayError",
    "ChopBatchReplayResult",
    "replay_ordinary_chop_batch",
]
