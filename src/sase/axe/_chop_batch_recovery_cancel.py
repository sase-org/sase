"""Persist clan cancellation for interrupted chop launch batches."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
from datetime import UTC


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

    Only evidence recorded for the requested *clan* may satisfy or veto the
    match. Generations recorded for other clans in a mixed-clan batch are
    ignored, while selecting either constituent clan still cancels the whole
    batch when that clan's own generation matches. A Rust ``False`` is
    authoritative. A Rust ``True`` still runs the Python policy, which can
    veto an older generation killing a batch that never recorded one.
    """
    rust_matched: bool | None = None
    try:
        from sase.core.axe_chop_facade import (
            CHOP_BATCH_SCHEMA_VERSION,
            chop_batch_generation_matches,
        )

        rust_matched = bool(
            chop_batch_generation_matches(
                {
                    "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                    "manifest": dict(manifest),
                    "clan": clan,
                    "generation": generation,
                }
            )
        )
    except Exception:
        rust_matched = None
    if rust_matched is False:
        return False
    # A Rust True still runs the Python policy below so an older generation
    # cannot cancel a batch that never recorded one. The current core pin
    # misses that veto.
    if not generation:
        return True
    members = (
        manifest.get("members") if isinstance(manifest.get("members"), list) else []
    )
    scoped_generations: set[str] = set()
    for item in members or []:
        if not isinstance(item, Mapping):
            continue
        item_clan = item.get("clan")
        if isinstance(item_clan, str) and item_clan and item_clan != clan:
            continue
        item_generation = item.get("clan_generation")
        if isinstance(item_generation, str) and item_generation:
            # Members without a clan field are legacy single-clan evidence and
            # count toward the requested clan; members of another clan are
            # skipped above so they can neither satisfy nor veto the match.
            scoped_generations.add(item_generation)
    if not scoped_generations:
        top_clan = manifest.get("clan", manifest.get("clan_name"))
        top_generation = manifest.get("clan_generation")
        if isinstance(top_generation, str) and top_generation:
            if isinstance(top_clan, str) and top_clan and top_clan != clan:
                pass
            elif not any(
                isinstance(item, Mapping)
                and isinstance(item.get("clan"), str)
                and item.get("clan")
                for item in members or []
            ):
                scoped_generations.add(top_generation)
    if scoped_generations:
        if generation not in scoped_generations:
            # A reused clan name in another generation must not cancel this batch,
            # and a wrong generation that happens to belong to another clan must
            # not cancel the selected clan either.
            return False
        return True
    batch_started = _batch_started_at(manifest)
    generation_started = _generation_started_at(generation)
    if (
        batch_started is not None
        and generation_started is not None
        and generation_started < batch_started
    ):
        # No recorded generation for the selected clan, but the kill provably
        # predates the batch: do not cancel.
        return False
    return True


def _batch_started_at(manifest: Mapping[str, Any]) -> Any:
    from datetime import datetime, timezone

    for value in (
        manifest.get("created_at"),
        (manifest.get("run") or {}).get("run_started_at")
        if isinstance(manifest.get("run"), Mapping)
        else None,
    ):
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        except ValueError:
            continue
    return None


def _generation_started_at(generation: str) -> Any:
    from datetime import datetime, timezone

    digits = "".join(character for character in generation if character.isdigit())
    if len(digits) < 14:
        return None
    try:
        return datetime.strptime(digits[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


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
