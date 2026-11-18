"""Persist clan cancellation for interrupted chop launch batches."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_shared import (
    batch_clan,
    batch_needs_resume,
    emit_batch_notice,
)
from .chop_batch_store import ChopBatchError


def cancel_chop_batches_for_clan(
    clan: str,
    *,
    generation: str | None = None,
    reason: str,
    routine: str | None = None,
    job: str | None = None,
) -> list[dict[str, Any]]:
    """Persist explicit clan-generation cancellation for matching batches.

    This is the shared backend operation every clan/bulk kill entry point
    must call before member expansion loses the container identity. It
    persists cancellation first so a later recovery permanently discards
    the remaining launch intent, then typed coordinator cancellation
    observes the same state. Killing an individual member must not call
    this; only an explicit clan-container kill does.
    """
    from .state import list_lumberjack_names

    cancelled: list[dict[str, Any]] = []
    if not clan:
        return cancelled
    routines = [routine] if routine else _safe_list_routines(list_lumberjack_names)
    for routine_name in routines:
        jobs = [job] if job else _safe_list_jobs(routine_name)
        for job_name in jobs:
            try:
                batches = chop_batch_store.list_pending_chop_batches(
                    routine_name, job_name
                )
            except Exception:
                continue
            for manifest in batches:
                batch_id = str(manifest.get("batch_id") or "")
                if not batch_id or not batch_needs_resume(manifest):
                    continue
                if batch_clan(manifest) != clan:
                    continue
                if generation is not None and not _generation_matches(
                    manifest, generation
                ):
                    continue
                try:
                    updated = chop_batch_store.apply_chop_batch_event(
                        routine_name,
                        job_name,
                        batch_id,
                        "cancel_clan_generation",
                        reason=reason or f"explicit clan kill of {clan}",
                    )
                except ChopBatchError:
                    continue
                emit_batch_notice(
                    routine=routine_name,
                    job=job_name,
                    batch_id=batch_id,
                    event="cancelled",
                    launched=int(updated.get("counts", {}).get("launched", 0))
                    if isinstance(updated.get("counts"), Mapping)
                    else 0,
                    remaining=0,
                    clan=clan,
                )
                _cancel_linked_typed_bundle(updated, reason=reason)
                cancelled.append(
                    {"routine": routine_name, "job": job_name, "batch_id": batch_id}
                )
    return cancelled


def _safe_list_routines(list_fn: Callable[[], list[str]]) -> list[str]:
    try:
        return list(list_fn())
    except Exception:
        return []


def _safe_list_jobs(routine: str) -> list[str]:
    try:
        from .state import lumberjack_state_dir

        chops_dir = lumberjack_state_dir(routine) / "chops"
        if not chops_dir.exists():
            return []
        return sorted(d.name for d in chops_dir.iterdir() if d.is_dir())
    except Exception:
        return []


def _generation_matches(manifest: Mapping[str, Any], generation: str) -> bool:
    if not generation:
        return True
    stored = manifest.get("clan_generation")
    if isinstance(stored, str) and stored and stored != generation:
        return False
    members = manifest.get("members")
    if isinstance(members, list):
        generations = {
            str(item.get("clan_generation") or "")
            for item in members
            if isinstance(item, Mapping) and item.get("clan_generation")
        }
        if generations and generation not in generations:
            # A reused clan name in another generation must not cancel this batch.
            return False
    return True


def _cancel_linked_typed_bundle(manifest: Mapping[str, Any], *, reason: str) -> None:
    bundle_ref = manifest.get("typed_bundle")
    if not isinstance(bundle_ref, Mapping):
        return
    try:
        from pathlib import Path

        from sase.agent.direct_typed_launch import typed_launch_bundle_dir
        from sase.agent.launch_admission import cancel_typed_launch_request

        bundle_id = str(bundle_ref.get("bundle_id") or "")
        if not bundle_id:
            return
        bundle_dir: Path = typed_launch_bundle_dir(bundle_id)
        try:
            cancel_typed_launch_request(bundle_dir, reason=reason)
        except Exception:
            pass
    except Exception:
        pass
