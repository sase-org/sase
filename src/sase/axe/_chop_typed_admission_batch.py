"""Resume typed chop batches and reconstruct their launch rows."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.agent.launch_admission_store import read_json

from ._chop_typed_admission_dispatch import make_axe_chop_agent_dispatcher
from ._chop_typed_admission_mirroring import (
    mirror_typed_dispatch_start,
    mirror_typed_launch,
    mirror_typed_unit_results,
)
from ._chop_typed_admission_utils import (
    AXE_CHOP_SOURCE_SURFACE,
    chop_batch_cancelled_for_typed_request,
    int_or_none,
    unit_metadata,
)


@dataclass(frozen=True)
class _TypedChopBatchResume:
    """Typed admission result plus the chop rows mirrored from its journal."""

    launches: tuple[dict[str, Any], ...]
    typed_admission: dict[str, Any]
    admission_result: Any
    paused: bool = False
    waiting: bool = False


def _result_from_receipt(request_id: str, receipt: Mapping[str, Any] | None) -> Any:
    if receipt is None:
        return SimpleNamespace(
            request_id=request_id,
            results=[],
            summary=None,
            unit_results=(),
            plan_digest=None,
            admission_complete=False,
            paused=False,
        )
    raw_summary = receipt.get("summary")
    summary_data = raw_summary if isinstance(raw_summary, Mapping) else {}
    summary = SimpleNamespace(
        total=int_or_none(summary_data.get("total")) or 0,
        eligible=int_or_none(summary_data.get("eligible")) or 0,
        launched=int_or_none(summary_data.get("launched")) or 0,
        skipped=int_or_none(summary_data.get("skipped")) or 0,
        condition_errors=int_or_none(summary_data.get("condition_errors")) or 0,
        launch_errors=int_or_none(summary_data.get("launch_errors")) or 0,
    )
    raw_units = receipt.get("units")
    unit_results = (
        tuple(
            SimpleNamespace(
                logical_id=str(item.get("logical_id") or ""),
                outcome=str(item.get("outcome") or ""),
                message=str(item.get("message") or ""),
            )
            for item in raw_units
            if isinstance(item, Mapping)
        )
        if isinstance(raw_units, list)
        else ()
    )
    return SimpleNamespace(
        request_id=request_id,
        results=[],
        summary=summary,
        unit_results=unit_results,
        plan_digest=str(receipt.get("plan_digest") or "") or None,
        admission_complete=bool(receipt.get("complete")),
        paused=False,
    )


def _typed_admission_record(
    *,
    bundle_dir: Path,
    payload: Mapping[str, Any],
    typed_plan: Any,
) -> dict[str, Any]:
    metadata = unit_metadata(payload)
    units: list[dict[str, Any]] = []
    for unit in typed_plan.units:
        unit_meta = metadata.get(unit.logical_id, {})
        units.append(
            {
                "logical_id": unit.logical_id,
                "source_order": int(unit.source_order),
                "proposal_index": unit_meta.get("proposal_index"),
                "proposal_id": unit_meta.get("proposal_id"),
                "dedupe_key": unit_meta.get("dedupe_key"),
                "wait_logical_id": unit_meta.get("wait_logical_id"),
            }
        )
    return {
        "request_id": str(payload.get("request_id") or ""),
        "bundle_dir": str(bundle_dir),
        "plan_digest": typed_plan.content_digest,
        "plan_schema_version": typed_plan.schema_version,
        "source_surface": AXE_CHOP_SOURCE_SURFACE,
        "units": units,
    }


def resume_typed_chop_batch(
    routine: str,
    job: str,
    batch_id: str,
    *,
    launch_agents_from_cwd_fn: Callable[..., Any] | None = None,
    launch_recorded_fn: Callable[[dict[str, Any]], None] | None = None,
    pause_requested_fn: Callable[[], bool] | None = None,
    spawn_coordinator: bool = True,
    ownership_acquired: bool = False,
) -> _TypedChopBatchResume:
    """Resume one typed chop batch from its frozen admission bundle.

    The admission journal remains the per-unit source of truth. The outer chop
    batch mirrors receipt outcomes so routine recovery can find the original
    run without rebuilding its prompts or typed plan.
    """
    from sase.ace.hooks.processes import is_process_running
    from sase.agent.direct_typed_launch import typed_launch_bundle_dir
    from sase.agent.launch_admission import dispatch_typed_launch_request
    from sase.agent.launch_admission_store import (
        RECEIPT_FILENAME,
        STARTED_FILENAME,
        admission_dir as typed_admission_dir,
    )
    from sase.agent.launch_admission_request_data import typed_plan_from_request
    from sase.agent.launch_request_response import read_launch_request
    from sase.agent.launch_request_types import LaunchRequestError

    from . import chop_batch_store

    manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
    bundle_ref = manifest.get("typed_bundle")
    if not isinstance(bundle_ref, Mapping):
        raise LaunchRequestError(
            "invalid_request", batch_id, "chop batch has no typed admission bundle"
        )
    bundle_id = str(bundle_ref.get("bundle_id") or "")
    bundle_digest = str(bundle_ref.get("bundle_digest") or "")
    if not bundle_id or not bundle_digest:
        raise LaunchRequestError(
            "invalid_request", batch_id, "typed bundle reference is incomplete"
        )
    bundle_dir = typed_launch_bundle_dir(bundle_id)
    payload = read_launch_request(bundle_dir)
    typed_plan = typed_plan_from_request(payload)
    if (
        str(payload.get("request_id") or "") != bundle_id
        or str(payload.get("source_surface") or "") != AXE_CHOP_SOURCE_SURFACE
        or str(payload.get("plan_digest") or "") != bundle_digest
        or typed_plan.content_digest != bundle_digest
    ):
        raise LaunchRequestError(
            "invalid_request",
            str(bundle_dir),
            "typed bundle identity or digest does not match the chop batch",
        )

    typed_admission = _typed_admission_record(
        bundle_dir=bundle_dir,
        payload=payload,
        typed_plan=typed_plan,
    )
    outer_owner = ownership_acquired or chop_batch_store.acquire_chop_batch_ownership(
        routine, job, batch_id, owner="typed-admission-resume"
    )
    if not outer_owner:
        receipt = read_json(typed_admission_dir(bundle_dir) / RECEIPT_FILENAME)
        result = _result_from_receipt(bundle_id, receipt)
        mirror_typed_unit_results(routine, job, batch_id, payload, result.unit_results)
        return _TypedChopBatchResume(
            launches=(),
            typed_admission=typed_admission,
            admission_result=result,
            waiting=True,
        )

    try:
        typed_root = typed_admission_dir(bundle_dir)
        started = read_json(typed_root / STARTED_FILENAME)
        coordinator_pid = started.get("pid") if isinstance(started, Mapping) else None
        if (
            isinstance(started, Mapping)
            and str(started.get("request_id") or "") == bundle_id
            and str(started.get("plan_digest") or "") == bundle_digest
            and isinstance(coordinator_pid, int)
            and coordinator_pid > 0
            and is_process_running(coordinator_pid)
        ):
            receipt = read_json(typed_root / RECEIPT_FILENAME)
            result = _result_from_receipt(bundle_id, receipt)
            mirror_typed_unit_results(
                routine, job, batch_id, payload, result.unit_results
            )
            return _TypedChopBatchResume(
                launches=(),
                typed_admission=typed_admission,
                admission_result=result,
                waiting=True,
            )

        manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
        if manifest.get("status") == "complete":
            receipt = read_json(typed_root / RECEIPT_FILENAME)
            result = _result_from_receipt(bundle_id, receipt)
            return _TypedChopBatchResume(
                launches=tuple(
                    _reconstruct_typed_launches(
                        routine, job, batch_id, typed_admission, typed_root
                    )
                ),
                typed_admission=typed_admission,
                admission_result=result,
            )
        if manifest.get("status") == "cancelled":
            receipt = read_json(typed_root / RECEIPT_FILENAME)
            result = _result_from_receipt(bundle_id, receipt)
            return _TypedChopBatchResume(
                launches=(),
                typed_admission=typed_admission,
                admission_result=result,
            )
        if manifest.get("status") == "paused":
            chop_batch_store.apply_chop_batch_event(routine, job, batch_id, "resume")

        replay_linkage_proven_dispatches(
            routine,
            job,
            batch_id,
            bundle_dir=bundle_dir,
            payload=payload,
            typed_plan=typed_plan,
        )

        recorded: list[dict[str, Any]] = []

        def _begin_dispatch(metadata: Mapping[str, Any]) -> bool:
            return mirror_typed_dispatch_start(routine, job, batch_id, metadata)

        def _record(launch: dict[str, Any]) -> None:
            recorded.append(launch)
            mirror_typed_launch(routine, job, batch_id, launch)
            if launch_recorded_fn is not None:
                launch_recorded_fn(launch)

        dispatcher = make_axe_chop_agent_dispatcher(
            payload,
            launch_agents_from_cwd_fn=launch_agents_from_cwd_fn,
            dispatch_started_fn=_begin_dispatch,
            launch_recorded_fn=_record,
            bundle_dir=bundle_dir,
        )
        result = dispatch_typed_launch_request(
            bundle_dir,
            payload,
            agent_dispatcher=dispatcher,
            spawn_coordinator=spawn_coordinator,
            pause_requested=pause_requested_fn,
            cancelled=lambda: chop_batch_cancelled_for_typed_request(payload),
        )
        mirror_typed_unit_results(routine, job, batch_id, payload, result.unit_results)
        paused = bool(result.paused)
        if paused:
            current = chop_batch_store.load_chop_batch(routine, job, batch_id)
            if current.get("status") in {"open", "paused"}:
                paused_manifest = chop_batch_store.apply_chop_batch_event(
                    routine,
                    job,
                    batch_id,
                    "request_pause",
                    reason="cooperative stop requested during typed admission",
                )
                from ._chop_batch_recovery_shared import (
                    batch_clan,
                    emit_batch_notice,
                    summarize_manifest,
                )

                counts = summarize_manifest(paused_manifest)
                emit_batch_notice(
                    routine=routine,
                    job=job,
                    batch_id=batch_id,
                    event="interrupted",
                    launched=counts["launched"],
                    remaining=counts["remaining"],
                    clan=batch_clan(paused_manifest),
                    reason="cooperative stop requested during typed admission",
                )
        launches = list(recorded)
        if result.admission_complete:
            launches = _merge_launch_rows(
                launches,
                _reconstruct_typed_launches(
                    routine, job, batch_id, typed_admission, typed_root
                ),
            )
        return _TypedChopBatchResume(
            launches=tuple(launches),
            typed_admission=typed_admission,
            admission_result=result,
            paused=paused,
            waiting=not result.admission_complete and not paused,
        )
    finally:
        # Release only executorship this call acquired. A recovery caller
        # that delegated its ownership still needs the batch (and its notice
        # outbox) for history merges and finish notices; it releases after.
        if not ownership_acquired:
            chop_batch_store.release_and_retire_chop_batch(routine, job, batch_id)


def replay_linkage_proven_dispatches(
    routine: str,
    job: str,
    batch_id: str,
    *,
    bundle_dir: Path,
    payload: Mapping[str, Any],
    typed_plan: Any,
) -> int:
    """Replay lost acknowledgements for linkage-proven typed dispatches.

    A stop between spawn and acknowledgement leaves a unit journaled as
    ``dispatching`` with no result. The admission planner cannot tell that
    state from a failed launch, so resume would skip a real spawned agent
    and drop it from the run history. The durable chop-agent linkage record
    written at spawn proves the launch the way the ordinary path's
    ``matched_spawn`` observation does: journal ``launched`` with the same
    entry shape the engine writes itself, store the unit receipt the planner
    reconciles, and release the dispatch hold. Units that already have a
    receipt file stay owned by the planner's ``record_launched`` path.
    Returns the number of units folded. Best effort: any lookup failure
    degrades to no fold so history can never break a resume.
    """
    try:
        from sase.agent.launch_admission_store import (
            LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
            UNITS_DIRNAME,
            admission_dir as typed_admission_dir,
            append_journal,
            next_journal_seq,
            read_journal,
            write_unit_receipt,
        )
        from sase.agent.launch_hold import release_unit_hold_if_terminal
        from sase.core.agent_launch_facade import (
            dispatch_fingerprint,
            reconcile_admission_journal,
        )

        from . import chop_batch_store
        from .chop_agents import (
            ChopAgentRecordsIncompleteError,
            get_chop_agent_records_strict,
        )

        root = typed_admission_dir(bundle_dir)
        states = reconcile_admission_journal(read_journal(root))
        metadata = unit_metadata(payload)
        try:
            records = get_chop_agent_records_strict(
                routine, chop_name=job, run_id=batch_id
            )
        except ChopAgentRecordsIncompleteError:
            # Uncertain linkage must not be treated as proof of absence:
            # leave dispatching units for a later retry once storage is readable.
            return 0
        except Exception:
            return 0
        by_index: dict[int, Any] = {}
        by_proposal_id: dict[str, Any] = {}
        for record in records or []:
            proposal_index = getattr(record, "proposal_index", None)
            if isinstance(proposal_index, int) and not isinstance(proposal_index, bool):
                by_index.setdefault(proposal_index, record)
            proposal_id = getattr(record, "proposal_id", "")
            if isinstance(proposal_id, str) and proposal_id:
                by_proposal_id.setdefault(proposal_id, record)
        try:
            manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
            members = manifest.get("members")
        except Exception:
            members = None
        names_by_index: dict[int, str] = {}
        if isinstance(members, list):
            for member in members:
                if not isinstance(member, Mapping):
                    continue
                source_index = member.get("source_index")
                agent_name = str(member.get("agent_name") or "")
                if (
                    isinstance(source_index, int)
                    and not isinstance(source_index, bool)
                    and agent_name
                ):
                    names_by_index.setdefault(source_index, agent_name)
        folded = 0
        request_id = str(payload.get("request_id") or "")
        for unit in typed_plan.units:
            try:
                state = states.get(unit.logical_id) or {}
                if str(state.get("phase") or "") != "dispatching":
                    continue
                receipt_path = root / UNITS_DIRNAME / f"{unit.logical_id}.json"
                if receipt_path.is_file():
                    continue
                unit_meta = metadata.get(unit.logical_id) or {}
                linkage: Any = None
                proposal_index = unit_meta.get("proposal_index")
                if isinstance(proposal_index, int) and not isinstance(
                    proposal_index, bool
                ):
                    linkage = by_index.get(proposal_index)
                if linkage is None:
                    proposal_id = unit_meta.get("proposal_id")
                    if isinstance(proposal_id, str) and proposal_id:
                        linkage = by_proposal_id.get(proposal_id)
                if linkage is None:
                    continue
                pid = getattr(linkage, "pid", None)
                if not isinstance(pid, int) or isinstance(pid, bool):
                    continue
                agent_name = ""
                if isinstance(proposal_index, int) and not isinstance(
                    proposal_index, bool
                ):
                    agent_name = names_by_index.get(proposal_index, "")
                if not agent_name:
                    continue
                fingerprint = dispatch_fingerprint(
                    typed_plan.content_digest, unit.logical_id, unit.payload
                )
                entry = {
                    "schema_version": LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
                    "seq": next_journal_seq(root),
                    "logical_id": unit.logical_id,
                    "phase": "launched",
                    "recorded_at_unix": time.time(),
                    "fingerprint": fingerprint,
                    "identity": agent_name,
                }
                append_journal(root, entry)
                write_unit_receipt(
                    root,
                    logical_id=unit.logical_id,
                    fingerprint=fingerprint,
                    identity=agent_name,
                    unit=unit,
                )
                release_unit_hold_if_terminal(unit, request_id)
                folded += 1
            except Exception:
                continue
        return folded
    except Exception:
        return 0


def _reconstruct_typed_launches(
    routine: str,
    job: str,
    run_id: str,
    typed_admission: Mapping[str, Any],
    typed_root: Path,
) -> list[dict[str, Any]]:
    from sase.agent.launch_admission_store import RECEIPT_FILENAME

    receipt = read_json(typed_root / RECEIPT_FILENAME)
    if not isinstance(receipt, Mapping) or not receipt.get("complete"):
        return []
    from ._chop_lifecycle_typed_admission import typed_admission_reconciliation
    from .chop_agents import get_chop_agent_records
    from .state import ChopRunEntry

    reconciliation = typed_admission_reconciliation(
        entry=ChopRunEntry(
            run_id=run_id,
            lumberjack_name=routine,
            chop_name=job,
            started_at="",
            finished_at=None,
            duration_ms=0,
            status="running",
            typed_admission=dict(typed_admission),
        ),
        records=get_chop_agent_records(routine, chop_name=job, run_id=run_id),
    )
    return [dict(launch) for launch in reconciliation.launches or []]


def _merge_launch_rows(
    current: Sequence[Mapping[str, Any]],
    reconstructed: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for launch in (*current, *reconstructed):
        row = dict(launch)
        key = (
            str(row.get("index") or ""),
            str(row.get("agent_name") or ""),
            str(row.get("pid") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged
