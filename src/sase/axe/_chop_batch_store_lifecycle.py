"""Pending-batch lifecycle: listing, deletion, and run-history retirement."""

from __future__ import annotations

import errno
import os
from typing import Any

from ._chop_batch_store_batches import load_chop_batch
from ._chop_batch_store_clan import (
    manifest_clans,
    read_clan_batch_index,
    update_clan_batch_index,
)
from ._chop_batch_store_ownership import release_chop_batch_ownership
from ._chop_batch_store_paths import (
    archived_chop_batch_path,
    chop_batch_attempts_path,
    chop_batch_notices_path,
    chop_batch_owner_path,
    chop_batch_path,
    chop_batches_dir,
    clan_batch_index_lock_path,
    clan_batch_index_path,
    mutation_lock_path,
    ownership_lock_path,
)
from .state import best_effort_test_state_write_allowed
from ._chop_batch_store_shared import (
    CHOP_BATCH_ATTEMPTS_SUFFIX,
    CHOP_BATCH_FILENAME_SUFFIX,
    CHOP_BATCH_NOTICES_SUFFIX,
    MAX_CLAN_BATCH_INDEX_ENTRIES,
    MAX_PENDING_BATCHES,
    ChopBatchError,
    fsync_dir,
    locked,
    read_json_object,
    read_owner_record,
    pid_is_live,
)


def list_pending_chop_batches(
    routine: str,
    job: str,
    *,
    limit: int = MAX_PENDING_BATCHES,
    repair_index: bool = True,
    retire_terminal: bool = True,
) -> list[dict[str, Any]]:
    """Enumerate stored batch manifests, newest filename first.

    Settled manifests do not consume the unfinished-batch bound. Old settled
    files are moved to run history as they are encountered; corrupt or
    unreadable manifests are skipped so one bad file cannot block recovery
    of the rest. Pass ``repair_index=False, retire_terminal=False`` for a
    strictly read-only enumeration that changes no filesystem state (dry-run
    and query helpers must use the read-only form).
    """
    if limit <= 0:
        return []
    directory = chop_batches_dir(routine, job)
    try:
        candidates = sorted(
            (
                path
                for path in directory.iterdir()
                if path.name.endswith(CHOP_BATCH_FILENAME_SUFFIX)
            ),
            key=lambda path: path.name,
            reverse=True,
        )
    except OSError:
        return []
    batches: list[dict[str, Any]] = []
    for path in candidates:
        batch_id = path.name[: -len(CHOP_BATCH_FILENAME_SUFFIX)]
        try:
            manifest = load_chop_batch(routine, job, batch_id)
        except ChopBatchError:
            continue
        if _batch_is_terminal(manifest):
            if batch_has_unsettled_cancelled_dispatch(manifest):
                if repair_index:
                    update_clan_batch_index(
                        routine, job, batch_id, set(), manifest_clans(manifest)
                    )
                batches.append(manifest)
                if len(batches) >= limit:
                    break
                continue
            if _has_pending_chop_batch_notices(routine, job, batch_id):
                batches.append(manifest)
                if len(batches) >= limit:
                    break
                continue
            if retire_terminal:
                retire_chop_batch(routine, job, batch_id)
            continue
        elif _batch_has_dispatch_work(manifest):
            if repair_index:
                update_clan_batch_index(
                    routine, job, batch_id, set(), manifest_clans(manifest)
                )
            batches.append(manifest)
        if len(batches) >= limit:
            break
    return batches


def delete_chop_batch(routine: str, job: str, batch_id: str) -> bool:
    """Delete one pending batch and its sidecars."""
    manifest_path = chop_batch_path(routine, job, batch_id)
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    sidecars = (
        chop_batch_notices_path(routine, job, batch_id),
        chop_batch_attempts_path(routine, job, batch_id),
    )
    with locked(mutation_lock_path(routine, job)):
        missing = not manifest_path.exists()
        manifest = None
        if not missing:
            try:
                manifest = load_chop_batch(routine, job, batch_id)
            except ChopBatchError:
                pass
        for path in (manifest_path, owner_path, *sidecars):
            try:
                path.unlink()
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise ChopBatchError(
                        f"cannot delete batch {batch_id!r}: {exc}"
                    ) from exc
        if manifest is not None:
            update_clan_batch_index(
                routine, job, batch_id, manifest_clans(manifest), set()
            )
    return not missing


def retire_chop_batch(routine: str, job: str, batch_id: str) -> bool:
    """Move a settled, unowned batch and its evidence into bounded run history."""
    manifest_path = chop_batch_path(routine, job, batch_id)
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    notice_path = chop_batch_notices_path(routine, job, batch_id)
    attempts_path = chop_batch_attempts_path(routine, job, batch_id)
    owner_lock = ownership_lock_path(routine, job)
    with locked(mutation_lock_path(routine, job)):
        try:
            manifest = load_chop_batch(routine, job, batch_id)
        except ChopBatchError:
            return False
        if not _batch_is_terminal(manifest) or _has_pending_chop_batch_notices(
            routine, job, batch_id
        ):
            return False
        if batch_has_unsettled_cancelled_dispatch(manifest):
            return False
        with locked(owner_lock):
            current_owner = read_owner_record(owner_path)
            if current_owner is not None and pid_is_live(current_owner.get("pid")):
                return False
            destination = archived_chop_batch_path(routine, job, batch_id)
            if not best_effort_test_state_write_allowed(
                destination, category="axe-chop-state"
            ):
                return False
            destination.parent.mkdir(parents=True, exist_ok=True)
            for source, target in (
                (manifest_path, destination),
                (
                    notice_path,
                    destination.with_name(f"{batch_id}{CHOP_BATCH_NOTICES_SUFFIX}"),
                ),
                (
                    attempts_path,
                    destination.with_name(f"{batch_id}{CHOP_BATCH_ATTEMPTS_SUFFIX}"),
                ),
            ):
                if source.exists():
                    os.replace(source, target)
            update_clan_batch_index(
                routine, job, batch_id, manifest_clans(manifest), set()
            )
            try:
                owner_path.unlink()
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise ChopBatchError(
                        f"cannot retire batch {batch_id!r}: {exc}"
                    ) from exc
            fsync_dir(manifest_path.parent)
            fsync_dir(destination.parent)
            return True


def delete_archived_chop_batch(routine: str, job: str, batch_id: str) -> bool:
    """Remove archived batch evidence when its bounded run history is pruned."""
    manifest_path = archived_chop_batch_path(routine, job, batch_id)
    paths = (
        manifest_path,
        manifest_path.with_name(f"{batch_id}{CHOP_BATCH_NOTICES_SUFFIX}"),
        manifest_path.with_name(f"{batch_id}{CHOP_BATCH_ATTEMPTS_SUFFIX}"),
    )
    existed = False
    for path in paths:
        try:
            path.unlink()
            existed = True
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise ChopBatchError(
                    f"cannot delete archived batch {batch_id!r}: {exc}"
                ) from exc
    if existed:
        fsync_dir(manifest_path.parent)
    return existed


def list_chop_batches_for_clan(clan: str) -> list[dict[str, str]]:
    """Return indexed pending batches for a clan without scanning job trees."""
    if not clan:
        return []
    index_path = clan_batch_index_path()
    with locked(clan_batch_index_lock_path()):
        index = read_clan_batch_index(index_path)
        raw_entries = index.get("clans")
        entries = raw_entries.get(clan, []) if isinstance(raw_entries, dict) else []
        if not isinstance(entries, list):
            return []
        if len(entries) > MAX_CLAN_BATCH_INDEX_ENTRIES:
            raise ChopBatchError(
                f"clan {clan!r} has more than {MAX_CLAN_BATCH_INDEX_ENTRIES} "
                "pending batches; refusing an unbounded cleanup scan"
            )
        return [
            {key: str(value) for key, value in item.items()}
            for item in entries
            if isinstance(item, dict)
        ]


def release_and_retire_chop_batch(routine: str, job: str, batch_id: str) -> bool:
    """Release this executor and archive the batch if its work is settled."""
    released = release_chop_batch_ownership(routine, job, batch_id)
    if released:
        retire_chop_batch(routine, job, batch_id)
    return released


def _has_pending_chop_batch_notices(routine: str, job: str, batch_id: str) -> bool:
    state = read_json_object(chop_batch_notices_path(routine, job, batch_id))
    episodes = state.get("episodes")
    if isinstance(episodes, dict):
        for episode in episodes.values():
            if not isinstance(episode, dict):
                continue
            events = episode.get("events")
            if isinstance(events, dict) and any(
                isinstance(event, dict) and not event.get("delivered")
                for event in events.values()
            ):
                return True
    return False


def _batch_is_terminal(manifest: dict[str, Any]) -> bool:
    return str(manifest.get("status") or "") in {"complete", "cancelled"}


def batch_has_unsettled_cancelled_dispatch(manifest: dict[str, Any]) -> bool:
    """Return whether a cancelled batch still owns in-flight dispatch evidence.

    A live crossing launch stays ``dispatching`` so its executor can settle it.
    When that executor dies, the batch must stay discoverable until dead-owner
    reconciliation proves spawn or no-spawn; it must never retire while a
    ``dispatching`` member remains.
    """
    if str(manifest.get("status") or "") != "cancelled":
        return False
    members = manifest.get("members")
    return isinstance(members, list) and any(
        isinstance(member, dict) and str(member.get("status") or "") == "dispatching"
        for member in members
    )


def _batch_has_dispatch_work(manifest: dict[str, Any]) -> bool:
    if _batch_is_terminal(manifest):
        return False
    members = manifest.get("members")
    return isinstance(members, list) and any(
        isinstance(member, dict)
        and str(member.get("status") or "pending") in {"pending", "dispatching"}
        for member in members
    )
