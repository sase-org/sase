"""Persist clan cancellation for interrupted chop launch batches."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.axe_chop_facade import (
    CHOP_BATCH_SCHEMA_VERSION,
    chop_batch_generation_matches,
)

from . import chop_batch_store
from ._chop_batch_recovery_shared import (
    batch_clans,
    batch_needs_resume,
    emit_batch_notice,
    summarize_manifest,
)
from .chop_batch_store import (
    ChopBatchError,
    list_chop_batches_for_clan,
    retire_chop_batch,
)


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
    cancelled: list[dict[str, Any]] = []
    if not clan:
        return cancelled
    if routine is not None and job is not None:
        candidates = [
            {
                "routine": routine,
                "job": job,
                "batch_id": str(item.get("batch_id") or ""),
            }
            for item in chop_batch_store.list_pending_chop_batches(routine, job)
        ]
    else:
        candidates = list_chop_batches_for_clan(clan)
        if routine is not None:
            candidates = [item for item in candidates if item.get("routine") == routine]
        if job is not None:
            candidates = [item for item in candidates if item.get("job") == job]
    for candidate in candidates:
        routine_name = str(candidate.get("routine") or "")
        job_name = str(candidate.get("job") or "")
        batch_id = str(candidate.get("batch_id") or "")
        if not routine_name or not job_name or not batch_id:
            continue
        try:
            manifest = chop_batch_store.load_chop_batch(
                routine_name, job_name, batch_id
            )
        except ChopBatchError:
            continue
        if not batch_needs_resume(manifest) or clan not in batch_clans(manifest):
            continue
        if generation is not None and not _generation_matches(
            manifest, clan, generation
        ):
            continue
        updated = chop_batch_store.apply_chop_batch_event(
            routine_name,
            job_name,
            batch_id,
            "cancel_clan_generation",
            reason=reason or f"explicit clan kill of {clan}",
        )
        counts = summarize_manifest(manifest)
        emit_batch_notice(
            routine=routine_name,
            job=job_name,
            batch_id=batch_id,
            event="cancelled",
            launched=counts["launched"],
            remaining=counts["remaining"],
            clan=clan,
        )
        _cancel_linked_typed_bundle(updated, reason=reason)
        retire_chop_batch(routine_name, job_name, batch_id)
        cancelled.append(
            {"routine": routine_name, "job": job_name, "batch_id": batch_id}
        )
    return cancelled


def _generation_matches(
    manifest: Mapping[str, Any], clan: str, generation: str
) -> bool:
    """Return whether an explicit kill targets this batch's clan generation.

    The shared Rust ``chop_batch_generation_matches`` policy is the single
    authority. Only evidence recorded for the requested *clan* may satisfy
    or veto the match. Generations recorded for other clans in a mixed-clan
    batch are ignored, while selecting either constituent clan still cancels
    the whole batch when that clan's own generation matches.
    """
    return bool(
        chop_batch_generation_matches(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": dict(manifest),
                "clan": clan,
                "generation": generation,
            }
        )
    )


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
        cancel_typed_launch_request(bundle_dir, reason=reason)
    except Exception as exc:
        run = manifest.get("run")
        if isinstance(run, Mapping):
            routine = str(run.get("routine") or "")
            job = str(run.get("job") or "")
            run_id = str(run.get("run_id") or "")
            if routine and job and run_id:
                try:
                    from .state import append_chop_run_output

                    append_chop_run_output(
                        routine,
                        job,
                        run_id,
                        "Outer batch cancellation was persisted, but typed bundle "
                        f"cancellation failed: {exc}\n",
                    )
                except Exception:
                    pass
        raise ChopBatchError(
            "outer batch cancellation was persisted, but linked typed bundle "
            f"cancellation failed: {exc}"
        ) from exc
