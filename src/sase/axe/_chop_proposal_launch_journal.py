"""Batch journal bookkeeping for ordinary chop proposal launches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.core.axe_chop_facade import (
    CHOP_BATCH_SCHEMA_VERSION,
    apply_chop_batch_transition,
)
from sase.core.process_identity import process_identity_token

from .chop_proposal_models import (
    PlannedChopProposal,
    resolve_wait_name,
)
from ._chop_proposal_launch_shared import wait_names_by_proposal_index


def _launch_descriptor(
    plan: PlannedChopProposal,
    result: Any,
    *,
    wait_on: int | str | None,
    wait_name: str | None,
) -> dict[str, Any]:
    proposal = plan.proposal
    actual_name = str(getattr(result, "agent_name", "") or plan.agent_name)
    timestamp = str(getattr(result, "timestamp", "") or "")
    artifacts_timestamp = (
        convert_timestamp_to_artifacts_format(timestamp) if timestamp else ""
    )
    pid = int(result.pid)
    return {
        "index": proposal.index,
        "id": proposal.proposal_id,
        "agent_name": actual_name,
        "clan": plan.clan,
        "member_id": plan.member_id,
        "pid": pid,
        "process_identity": process_identity_token(pid),
        "workspace": proposal.workspace,
        "workspace_num": int(getattr(result, "workspace_num", 0) or 0),
        "workspace_dir": str(getattr(result, "workspace_dir", "") or ""),
        "project_name": str(getattr(result, "project_name", "") or ""),
        "workflow_name": str(getattr(result, "workflow_name", "") or ""),
        "patch_name": str(getattr(result, "cl_name", "") or ""),
        "cl_name": str(getattr(result, "cl_name", "") or ""),
        "timestamp": timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "artifacts_dir": str(getattr(result, "artifacts_dir", "") or ""),
        "dedupe_key": proposal.dedupe_key,
        "wait_on": wait_on,
        "wait_name": wait_name,
    }


class OrdinaryLaunchJournal:
    """Mutable batch-journal state for one ordinary chop proposal launch."""

    def __init__(
        self,
        *,
        lumberjack_name: str,
        chop_name: str,
        batch_id: str | None,
        plans: Sequence[PlannedChopProposal],
        launch_recorded_fn: Callable[[dict[str, Any]], None] | None = None,
        pause_requested_fn: Callable[[], bool] | None = None,
        batch_cancelled_fn: Callable[[], bool] | None = None,
    ) -> None:
        self.lumberjack_name = lumberjack_name
        self.chop_name = chop_name
        self.batch_id = batch_id
        self.plans = plans
        self.wait_names = wait_names_by_proposal_index(plans)
        self.has_clan = any(plan.clan is not None for plan in plans)
        self.launch_recorded_fn = launch_recorded_fn
        self.pause_requested_fn = pause_requested_fn
        self.batch_cancelled_fn = batch_cancelled_fn
        self.names_by_index: dict[int, str] = {}
        self.names_by_id: dict[str, str] = {}
        self.proposal_indices_by_id: dict[str, int] = {}
        self.resolved_waits: dict[int, int | str | None] = {}
        self.skipped_indices: set[int] = set()
        self.launches_by_member: dict[int, dict[str, Any]] = {}
        self.published_launches: set[tuple[int, str, int]] = set()
        self.paused = False
        self.cancelled = False
        self.active_single_member: int | None = None

    def batch_event(
        self,
        event: str,
        *,
        member_index: int | None = None,
        reason: str | None = None,
    ) -> None:
        if self.batch_id is None:
            return
        from .chop_batch_store import apply_chop_batch_event

        manifest = apply_chop_batch_event(
            self.lumberjack_name,
            self.chop_name,
            self.batch_id,
            event,
            member_index=member_index,
            reason=reason,
        )
        if event == "request_pause":
            from ._chop_batch_recovery_shared import (
                batch_clan,
                emit_batch_notice,
                summarize_manifest,
            )

            counts = summarize_manifest(manifest)
            emit_batch_notice(
                routine=self.lumberjack_name,
                job=self.chop_name,
                batch_id=self.batch_id,
                event="interrupted",
                launched=counts["launched"],
                remaining=counts["remaining"],
                clan=batch_clan(manifest),
                reason=reason,
            )

    def prepare_member(
        self,
        member_index: int,
        *,
        request: Any | None = None,
        membership: Any | None = None,
        actual_name: str | None = None,
    ) -> None:
        if self.batch_id is None:
            return
        from .chop_batch_store import update_chop_batch

        evidence = getattr(request, "name_reservation", None)
        evidence_name = str(getattr(evidence, "agent_name", "") or "")
        planned_env = getattr(request, "extra_env", None) or {}
        if not actual_name:
            actual_name = evidence_name or str(
                planned_env.get("SASE_AGENT_PLANNED_NAME") or ""
            )
        generation = str(getattr(membership, "generation", "") or "")
        clan_name = str(getattr(membership, "clan_name", "") or "")

        def _update(manifest: dict[str, Any]) -> dict[str, Any]:
            member = manifest["members"][member_index]
            if evidence_name and actual_name and evidence_name != actual_name:
                raise RuntimeError(
                    "reserved agent name differs from the accepted chop plan: "
                    f"{evidence_name!r} != {actual_name!r}"
                )
            if actual_name:
                member["agent_name"] = actual_name
            if generation:
                if member.get("clan") and clan_name != member["clan"]:
                    raise RuntimeError(
                        "clan reservation differs from accepted chop plan: "
                        f"{clan_name!r} != {member['clan']!r}"
                    )
                stored_generation = str(member.get("clan_generation") or "")
                if stored_generation and stored_generation != generation:
                    raise RuntimeError(
                        "clan generation differs from the persisted chop plan: "
                        f"{stored_generation!r} != {generation!r}"
                    )
                member["clan_generation"] = generation
                generations = {
                    str(item.get("clan_generation") or "")
                    for item in manifest["members"]
                    if item.get("clan")
                }
                if generations == {generation}:
                    manifest["clan_generation"] = generation
            return apply_chop_batch_transition(
                {
                    "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                    "manifest": manifest,
                    "event": "begin_dispatch",
                    "member_index": member_index,
                }
            )

        update_chop_batch(self.lumberjack_name, self.chop_name, self.batch_id, _update)

    def journal_launch(
        self,
        member_index: int,
        plan: PlannedChopProposal,
        result: Any,
        *,
        request: Any | None = None,
        membership: Any | None = None,
    ) -> dict[str, Any]:
        from .chop_batch_store import load_chop_batch

        effective_wait = self.resolved_waits.get(
            plan.proposal.index,
            plan.proposal.wait_on,
        )
        try:
            wait_name = resolve_wait_name(
                effective_wait, self.names_by_index, self.names_by_id
            )
        except KeyError:
            wait_name = None
        launch = _launch_descriptor(
            plan,
            result,
            wait_on=effective_wait,
            wait_name=wait_name or self.wait_names.get(plan.proposal.index),
        )
        if self.batch_id is not None:
            manifest = load_chop_batch(
                self.lumberjack_name, self.chop_name, self.batch_id
            )
            status = str(manifest["members"][member_index]["status"])
            if status == "pending":
                self.prepare_member(
                    member_index,
                    request=request,
                    membership=membership,
                    actual_name=str(launch["agent_name"]),
                )
                status = "dispatching"
            if status == "dispatching":
                self.batch_event("acknowledge_launch", member_index=member_index)
            elif status != "launched":
                raise RuntimeError(
                    f"cannot record launch for batch member in {status!r} state"
                )
        self.launches_by_member[member_index] = launch
        self.names_by_index[plan.proposal.index] = str(launch["agent_name"])
        if plan.proposal.proposal_id is not None:
            self.names_by_id[plan.proposal.proposal_id] = str(launch["agent_name"])
        key = (
            int(launch["index"]),
            str(launch["agent_name"]),
            int(launch["pid"]),
        )
        if key not in self.published_launches:
            self.published_launches.add(key)
            if self.launch_recorded_fn is not None:
                self.launch_recorded_fn(launch)
        return launch

    def before_agent_spawn(
        self,
        segment_index: int,
        slot_index: int,
        request: Any,
        membership: Any | None = None,
    ) -> None:
        if slot_index != 0:
            raise RuntimeError(
                "one chop proposal expanded into multiple launch slots; "
                "proposal fan-out is not supported by the batch journal"
            )
        member_index = segment_index if self.has_clan else self.active_single_member
        if member_index is None or not 0 <= member_index < len(self.plans):
            raise RuntimeError(f"invalid chop launch source slot {segment_index}")
        self.prepare_member(
            member_index,
            request=request,
            membership=membership,
        )

    def plan_prepared(
        self,
        segment_index: int,
        slot_index: int,
        agent_name: str,
        membership: Any | None = None,
    ) -> None:
        if slot_index != 0:
            raise RuntimeError(
                "one chop proposal expanded into multiple launch slots; "
                "proposal fan-out is not supported by the batch journal"
            )
        if not self.has_clan:
            return
        if not 0 <= segment_index < len(self.plans):
            raise RuntimeError(f"invalid chop launch source slot {segment_index}")
        if self.batch_id is None:
            return
        from .chop_batch_store import update_chop_batch

        generation = str(getattr(membership, "generation", "") or "")
        clan_name = str(getattr(membership, "clan_name", "") or "")

        def _update(manifest: dict[str, Any]) -> dict[str, Any]:
            member = manifest["members"][segment_index]
            if member.get("clan") and clan_name != member["clan"]:
                raise RuntimeError(
                    "clan preflight differs from accepted chop plan: "
                    f"{clan_name!r} != {member['clan']!r}"
                )
            stored_generation = str(member.get("clan_generation") or "")
            if generation and stored_generation and stored_generation != generation:
                raise RuntimeError(
                    "clan generation differs from the persisted chop plan: "
                    f"{stored_generation!r} != {generation!r}"
                )
            member["agent_name"] = agent_name
            if generation:
                member["clan_generation"] = generation
            clan_names = {
                str(item.get("clan") or "")
                for item in manifest["members"]
                if item.get("clan")
            }
            generations = {
                str(item.get("clan_generation") or "")
                for item in manifest["members"]
                if item.get("clan")
            }
            if len(clan_names) == 1 and len(generations) == 1 and "" not in generations:
                manifest["clan"] = next(iter(clan_names))
                manifest["clan_generation"] = next(iter(generations))
            return manifest

        update_chop_batch(self.lumberjack_name, self.chop_name, self.batch_id, _update)

    def record_agent_spawn(
        self,
        segment_index: int,
        slot_index: int,
        record: Any,
        membership: Any | None = None,
    ) -> None:
        if slot_index != 0:
            raise RuntimeError(
                "one chop proposal expanded into multiple launch slots; "
                "proposal fan-out is not supported by the batch journal"
            )
        member_index = segment_index if self.has_clan else self.active_single_member
        if member_index is None or not 0 <= member_index < len(self.plans):
            raise RuntimeError(f"invalid chop launch source slot {segment_index}")
        result = getattr(record, "result", None)
        if result is None:
            return
        self.journal_launch(
            member_index,
            self.plans[member_index],
            result,
            request=getattr(record, "request", None),
            membership=membership,
        )

    def pause_batch(self) -> None:
        if self.batch_cancelled_fn is not None and self.batch_cancelled_fn():
            self.cancelled = True
            return
        if self.paused:
            return
        self.paused = True
        self.batch_event("request_pause", reason="cooperative stop requested")

    def progress_kwargs(self) -> dict[str, Any]:
        return {
            "before_agent_spawn": self.before_agent_spawn,
            "on_agent_plan_prepared": self.plan_prepared,
            "on_agent_launch_recorded": self.record_agent_spawn,
            "pause_requested_fn": self.pause_requested_fn,
            "on_launch_paused": self.pause_batch,
        }

    def fallback_record(
        self,
        member_index: int,
        result: Any,
    ) -> dict[str, Any]:
        return self.journal_launch(
            member_index,
            self.plans[member_index],
            result,
        )


__all__ = ["OrdinaryLaunchJournal"]
