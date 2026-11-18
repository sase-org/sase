"""Create, load, and transition stored chop launch batches."""

from __future__ import annotations

import errno
import json
from collections.abc import Callable
from typing import Any

from sase.core.axe_chop_facade import (
    CHOP_BATCH_SCHEMA_VERSION,
    apply_chop_batch_transition,
    reconcile_chop_batch,
    summarize_chop_batch,
    validate_chop_batch_manifest,
)

from ._chop_batch_store_clan import manifest_clans, update_clan_batch_index
from ._chop_batch_store_ownership import (
    acquire_chop_batch_ownership,
    release_chop_batch_ownership,
)
from ._chop_batch_store_paths import (
    archived_chop_batch_path,
    chop_batch_path,
    ensure_chop_batches_dir,
    mutation_lock_path,
)
from ._chop_batch_store_shared import (
    ChopBatchCorruptError,
    ChopBatchError,
    ChopBatchExistsError,
    ChopBatchNotFoundError,
    atomic_write_manifest,
    locked,
    require_safe_batch_id,
)


class _ChopBatchOwnershipError(ChopBatchError):
    """A live executor already owns the batch being created."""


def create_chop_batch(
    routine: str,
    job: str,
    manifest: dict[str, Any],
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    """Persist a new batch, optionally claiming it before it becomes visible."""
    try:
        validated = validate_chop_batch_manifest(manifest)
    except ValueError as exc:
        raise ChopBatchCorruptError(f"batch manifest failed validation: {exc}") from exc
    batch_id = str(validated["batch_id"])
    require_safe_batch_id(batch_id)
    ensure_chop_batches_dir(routine, job)
    path = chop_batch_path(routine, job, batch_id)
    with locked(mutation_lock_path(routine, job)):
        if path.exists():
            raise ChopBatchExistsError(f"batch {batch_id!r} already exists")
        claimed = False
        if owner is not None:
            claimed = acquire_chop_batch_ownership(routine, job, batch_id, owner=owner)
            if not claimed:
                raise _ChopBatchOwnershipError(
                    f"batch {batch_id!r} already has a live executor"
                )
        try:
            atomic_write_manifest(path, validated)
            update_clan_batch_index(
                routine, job, batch_id, set(), manifest_clans(validated)
            )
        except BaseException:
            try:
                path.unlink()
            except OSError:
                pass
            if claimed:
                release_chop_batch_ownership(routine, job, batch_id)
            raise
    return validated


def load_chop_batch(routine: str, job: str, batch_id: str) -> dict[str, Any]:
    """Load and validate one batch manifest.

    Unknown schema versions and corrupt payloads raise
    :class:`ChopBatchCorruptError` so callers never dispatch from them.
    """
    path = chop_batch_path(routine, job, batch_id)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            archived_path = archived_chop_batch_path(routine, job, batch_id)
            try:
                raw = archived_path.read_bytes()
            except OSError as archived_exc:
                if archived_exc.errno == errno.ENOENT:
                    raise ChopBatchNotFoundError(
                        f"batch {batch_id!r} not found"
                    ) from archived_exc
                raise ChopBatchError(
                    f"cannot read batch {batch_id!r}: {archived_exc}"
                ) from archived_exc
        else:
            raise ChopBatchError(f"cannot read batch {batch_id!r}: {exc}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChopBatchCorruptError(
            f"batch {batch_id!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ChopBatchCorruptError(f"batch {batch_id!r} must be a JSON object")
    try:
        return validate_chop_batch_manifest(manifest)
    except ValueError as exc:
        raise ChopBatchCorruptError(
            f"batch {batch_id!r} failed validation: {exc}"
        ) from exc


def update_chop_batch(
    routine: str,
    job: str,
    batch_id: str,
    transform: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Atomically read, transform, validate, and rewrite one manifest."""
    ensure_chop_batches_dir(routine, job)
    path = chop_batch_path(routine, job, batch_id)
    with locked(mutation_lock_path(routine, job)):
        current = load_chop_batch(routine, job, batch_id)
        updated = transform(dict(current))
        if not isinstance(updated, dict):
            raise ChopBatchError("batch transform must return a manifest dict")
        try:
            validated = validate_chop_batch_manifest(updated)
        except ValueError as exc:
            raise ChopBatchCorruptError(
                f"batch {batch_id!r} update failed validation: {exc}"
            ) from exc
        atomic_write_manifest(path, validated)
        old_clans = manifest_clans(current)
        new_clans = manifest_clans(validated)
        if old_clans != new_clans:
            try:
                update_clan_batch_index(routine, job, batch_id, old_clans, new_clans)
            except BaseException:
                atomic_write_manifest(path, current)
                raise
    return validated


def apply_chop_batch_event(
    routine: str,
    job: str,
    batch_id: str,
    event: str,
    *,
    member_index: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Apply one Rust-owned state-machine event to a stored manifest."""

    def _apply(manifest: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "schema_version": CHOP_BATCH_SCHEMA_VERSION,
            "manifest": manifest,
            "event": event,
        }
        if member_index is not None:
            request["member_index"] = member_index
        if reason is not None:
            request["reason"] = reason
        return apply_chop_batch_transition(request)

    try:
        return update_chop_batch(routine, job, batch_id, _apply)
    except ValueError as exc:
        raise ChopBatchError(f"cannot apply batch event {event!r}: {exc}") from exc


def summarize_stored_batch(routine: str, job: str, batch_id: str) -> dict[str, Any]:
    """Return batch identity plus progress counts for a stored manifest."""
    manifest = load_chop_batch(routine, job, batch_id)
    try:
        return summarize_chop_batch(manifest)
    except ValueError as exc:
        raise ChopBatchError(f"cannot summarize batch {batch_id!r}: {exc}") from exc


def reconcile_stored_batch(
    routine: str,
    job: str,
    batch_id: str,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select the resume work for a stored batch from spawn observations."""
    manifest = load_chop_batch(routine, job, batch_id)
    try:
        return reconcile_chop_batch(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": manifest,
                "observations": list(observations),
            }
        )
    except ValueError as exc:
        raise ChopBatchError(f"cannot reconcile batch {batch_id!r}: {exc}") from exc
