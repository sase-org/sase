"""Stable, lazy import surface for launching chop proposals."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .chop_proposal_models import PlannedChopProposal, PreparedChopProposal


class ChopProposalLaunches(list[dict[str, Any]]):
    """Launch rows plus optional durable typed-admission metadata."""

    def __init__(
        self,
        launches: Sequence[dict[str, Any]] = (),
        *,
        typed_admission: dict[str, Any] | None = None,
        admission_result: Any | None = None,
        paused: bool = False,
        batch_id: str | None = None,
    ) -> None:
        super().__init__(launches)
        self.typed_admission = typed_admission
        self.admission_result = admission_result
        self.paused = paused
        self.batch_id = batch_id


def launch_chop_proposals(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    proposals: list[PreparedChopProposal],
    launch_agent_from_cwd_fn: Callable[..., Any] | None,
    launch_agents_from_cwd_fn: Callable[..., Any] | None = None,
    launch_plans: Sequence[PlannedChopProposal] | None = None,
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None = None,
    proposal_skipped_fn: (
        Callable[[PreparedChopProposal, str, int | str | None], None] | None
    ) = None,
    run_started_at: datetime | None = None,
    preflight: Any | None = None,
    batch_created_fn: Callable[[str], None] | None = None,
    pause_requested_fn: Callable[[], bool] | None = None,
) -> ChopProposalLaunches:
    """Load launch machinery only when a chop proposal is actually launched."""
    from .chop_proposal_launch_impl import (
        launch_chop_proposals as launch_chop_proposals_impl,
    )

    owned_batch_ids: list[str] = []

    def _batch_owner_registered(batch_id: str) -> None:
        owned_batch_ids.append(batch_id)

    try:
        return launch_chop_proposals_impl(
            lumberjack_name=lumberjack_name,
            chop_name=chop_name,
            run_id=run_id,
            proposals=proposals,
            launch_agent_from_cwd_fn=launch_agent_from_cwd_fn,
            launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
            launch_plans=launch_plans,
            launch_recorded_fn=launch_recorded_fn,
            proposal_skipped_fn=proposal_skipped_fn,
            run_started_at=run_started_at,
            preflight=preflight,
            batch_created_fn=batch_created_fn,
            pause_requested_fn=pause_requested_fn,
            batch_owner_registered_fn=_batch_owner_registered,
        )
    finally:
        if owned_batch_ids:
            from .chop_batch_store import release_and_retire_chop_batch

            for batch_id in owned_batch_ids:
                release_and_retire_chop_batch(lumberjack_name, chop_name, batch_id)


__all__ = ["ChopProposalLaunches", "launch_chop_proposals"]
