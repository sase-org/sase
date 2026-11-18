"""Crash-safe persistent store for interrupted chop launch batches.

A batch manifest freezes the accepted concrete launch plan before the first
dispatch so a routine or service-host stop can resume the original identities
instead of replanning. The Rust batch contract in ``sase_core::axe_chop``
owns validation, transitions, resume selection, and counts; this module owns
filesystem layout, atomic durability, and process-safe ownership. It never
reimplements the state machine.

Lock order (outermost first): admission lock, agent-name lock, batch mutation
lock, batch ownership lock. The mutation lock serializes read/transform/write
cycles; the ownership lock is a separate, short-held lock so cancellation can
persist while a member launch is in flight. Both locks pair an in-process
mutex with a dedicated cross-process ``flock`` file.

Layout (outside the prunable run-history payloads)::

    ~/.sase/axe/lumberjacks/{routine}/chops/{job}/pending_batches/
        {batch_id}.batch.json
        {batch_id}.owner.json
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.core.axe_chop_facade import (
    CHOP_BATCH_SCHEMA_VERSION,
    apply_chop_batch_transition,
    reconcile_chop_batch,
    summarize_chop_batch,
    validate_chop_batch_manifest,
)

from .state import best_effort_test_state_write_allowed as _writes_allowed
from .state import lumberjack_state_dir

CHOP_BATCH_DIRNAME = "pending_batches"
CHOP_BATCH_FILENAME_SUFFIX = ".batch.json"
CHOP_BATCH_OWNER_SUFFIX = ".owner.json"
CHOP_BATCH_NOTICES_SUFFIX = ".notices.json"
CHOP_BATCH_ATTEMPTS_SUFFIX = ".attempts.json"
CHOP_BATCH_MUTATION_LOCK_FILENAME = "pending_batches.lock"
CHOP_BATCH_OWNERSHIP_LOCK_FILENAME = "pending_batches.ownership.lock"

#: Upper bound for one recovery scan; the directory holds one small manifest
#: per interrupted batch, so this cap only bites on corruption or misuse.
MAX_PENDING_BATCHES = 256
MAX_CLAN_BATCH_INDEX_ENTRIES = 256

_MUTEXES_LOCK = threading.Lock()
_MUTEXES: dict[str, threading.Lock] = {}


class ChopBatchError(Exception):
    """Base error for chop batch store failures."""


class ChopBatchNotFoundError(ChopBatchError):
    """The requested batch manifest does not exist."""


class ChopBatchExistsError(ChopBatchError):
    """A batch manifest already exists for this batch id."""


class _ChopBatchOwnershipError(ChopBatchError):
    """A live executor already owns the batch being created."""


class ChopBatchCorruptError(ChopBatchError):
    """The stored batch manifest cannot be parsed or fails validation."""


def chop_batches_dir(routine: str, job: str) -> Path:
    """Return the pending-batch directory for one routine/job pair."""
    return lumberjack_state_dir(routine) / "chops" / job / CHOP_BATCH_DIRNAME


def chop_batch_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the manifest path for one batch."""
    _require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_FILENAME_SUFFIX}"


def chop_batch_owner_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the executor-ownership sidecar path for one batch."""
    _require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_OWNER_SUFFIX}"


def _chop_batch_notices_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the durable notification outbox beside one batch manifest."""
    _require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_NOTICES_SUFFIX}"


def _chop_batch_attempts_path(routine: str, job: str, batch_id: str) -> Path:
    """Return recovery attempt metadata beside one batch manifest."""
    _require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_ATTEMPTS_SUFFIX}"


def _archived_chop_batch_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the run-history copy of a settled batch manifest."""
    _require_safe_batch_id(batch_id)
    return (
        lumberjack_state_dir(routine)
        / "chops"
        / job
        / "runs"
        / f"{batch_id}{CHOP_BATCH_FILENAME_SUFFIX}"
    )


def _clan_batch_index_path() -> Path:
    return lumberjack_state_dir("") / "pending_batches_by_clan.json"


def _clan_batch_index_lock_path() -> Path:
    return lumberjack_state_dir("") / "pending_batches_by_clan.lock"


def ensure_chop_batches_dir(routine: str, job: str) -> Path:
    """Create the pending-batch directory for one routine/job pair."""
    directory = chop_batches_dir(routine, job)
    if _writes_allowed(directory, category="axe-chop-state"):
        directory.mkdir(parents=True, exist_ok=True)
    return directory


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
    _require_safe_batch_id(batch_id)
    ensure_chop_batches_dir(routine, job)
    path = chop_batch_path(routine, job, batch_id)
    with _locked(_mutation_lock_path(routine, job)):
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
            _atomic_write_manifest(path, validated)
            _update_clan_batch_index(
                routine, job, batch_id, set(), _manifest_clans(validated)
            )
        except BaseException:
            try:
                path.unlink()
            except OSError:
                pass
            if claimed:
                _release_chop_batch_ownership(routine, job, batch_id)
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
            archived_path = _archived_chop_batch_path(routine, job, batch_id)
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
    with _locked(_mutation_lock_path(routine, job)):
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
        _atomic_write_manifest(path, validated)
        old_clans = _manifest_clans(current)
        new_clans = _manifest_clans(validated)
        if old_clans != new_clans:
            try:
                _update_clan_batch_index(routine, job, batch_id, old_clans, new_clans)
            except BaseException:
                _atomic_write_manifest(path, current)
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


def list_pending_chop_batches(
    routine: str, job: str, *, limit: int = MAX_PENDING_BATCHES
) -> list[dict[str, Any]]:
    """Enumerate stored batch manifests, newest filename first.

    Settled manifests do not consume the unfinished-batch bound. Old settled
    files are moved to run history as they are encountered; corrupt or
    unreadable manifests are skipped so one bad file cannot block recovery
    of the rest.
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
            if not _has_pending_chop_batch_notices(routine, job, batch_id):
                retire_chop_batch(routine, job, batch_id)
                continue
            batches.append(manifest)
        elif _batch_has_dispatch_work(manifest):
            _update_clan_batch_index(
                routine, job, batch_id, set(), _manifest_clans(manifest)
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
        _chop_batch_notices_path(routine, job, batch_id),
        _chop_batch_attempts_path(routine, job, batch_id),
    )
    with _locked(_mutation_lock_path(routine, job)):
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
            _update_clan_batch_index(
                routine, job, batch_id, _manifest_clans(manifest), set()
            )
    return not missing


def retire_chop_batch(routine: str, job: str, batch_id: str) -> bool:
    """Move a settled, unowned batch and its evidence into bounded run history."""
    manifest_path = chop_batch_path(routine, job, batch_id)
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    notice_path = _chop_batch_notices_path(routine, job, batch_id)
    attempts_path = _chop_batch_attempts_path(routine, job, batch_id)
    owner_lock = _ownership_lock_path(routine, job)
    with _locked(_mutation_lock_path(routine, job)):
        try:
            manifest = load_chop_batch(routine, job, batch_id)
        except ChopBatchError:
            return False
        if not _batch_is_terminal(manifest) or _has_pending_chop_batch_notices(
            routine, job, batch_id
        ):
            return False
        with _locked(owner_lock):
            current_owner = _read_owner_record(owner_path)
            if current_owner is not None and _pid_is_live(current_owner.get("pid")):
                return False
            destination = _archived_chop_batch_path(routine, job, batch_id)
            if not _writes_allowed(destination, category="axe-chop-state"):
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
            _update_clan_batch_index(
                routine, job, batch_id, _manifest_clans(manifest), set()
            )
            try:
                owner_path.unlink()
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise ChopBatchError(
                        f"cannot retire batch {batch_id!r}: {exc}"
                    ) from exc
            _fsync_dir(manifest_path.parent)
            _fsync_dir(destination.parent)
            return True


def delete_archived_chop_batch(routine: str, job: str, batch_id: str) -> bool:
    """Remove archived batch evidence when its bounded run history is pruned."""
    manifest_path = _archived_chop_batch_path(routine, job, batch_id)
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
        _fsync_dir(manifest_path.parent)
    return existed


def list_chop_batches_for_clan(clan: str) -> list[dict[str, str]]:
    """Return indexed pending batches for a clan without scanning job trees."""
    if not clan:
        return []
    index_path = _clan_batch_index_path()
    with _locked(_clan_batch_index_lock_path()):
        index = _read_clan_batch_index(index_path)
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


def _manifest_clans(manifest: dict[str, Any]) -> set[str]:
    clans: set[str] = set()
    for key in ("clan", "clan_name"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            clans.add(value)
    members = manifest.get("members")
    if isinstance(members, list):
        for member in members:
            if isinstance(member, dict):
                clan = member.get("clan")
                if isinstance(clan, str) and clan:
                    clans.add(clan)
    return clans


def _update_clan_batch_index(
    routine: str,
    job: str,
    batch_id: str,
    old_clans: set[str],
    new_clans: set[str],
) -> None:
    path = _clan_batch_index_path()
    with _locked(_clan_batch_index_lock_path()):
        index = _read_clan_batch_index(path)
        clans = index.get("clans")
        if not isinstance(clans, dict):
            clans = {}
        entry = {"routine": routine, "job": job, "batch_id": batch_id}
        for clan in old_clans | new_clans:
            rows = clans.get(clan)
            if not isinstance(rows, list):
                rows = []
            rows = [
                item
                for item in rows
                if not (
                    isinstance(item, dict)
                    and item.get("routine") == routine
                    and item.get("job") == job
                    and item.get("batch_id") == batch_id
                )
            ]
            if clan in new_clans:
                rows.append(entry)
                if len(rows) > MAX_CLAN_BATCH_INDEX_ENTRIES:
                    raise ChopBatchError(
                        f"clan {clan!r} reached the bounded pending batch index "
                        f"limit ({MAX_CLAN_BATCH_INDEX_ENTRIES})"
                    )
            if rows:
                clans[clan] = rows
            else:
                clans.pop(clan, None)
        index["schema_version"] = 1
        index["clans"] = clans
        _atomic_write_manifest(path, index)


def _read_clan_batch_index(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return {"schema_version": 1, "clans": {}}
        raise ChopBatchError(f"cannot read pending batch clan index: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChopBatchCorruptError(
            f"pending batch clan index is corrupt: {exc}"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("clans"), dict)
    ):
        raise ChopBatchCorruptError("pending batch clan index has an invalid shape")
    return value


def increment_chop_batch_dispatch_attempt(
    routine: str, job: str, batch_id: str, member_index: int
) -> int:
    """Durably count a failed recovery dispatch for one accepted member."""
    path = _chop_batch_attempts_path(routine, job, batch_id)
    with _locked(_mutation_lock_path(routine, job)):
        data = _read_json_object(path)
        attempts = data.get("attempts")
        if not isinstance(attempts, dict):
            attempts = {}
        key = str(member_index)
        current = attempts.get(key, 0)
        count = (
            int(current)
            if isinstance(current, int) and not isinstance(current, bool)
            else 0
        )
        attempts[key] = count + 1
        _atomic_write_manifest(path, {"batch_id": batch_id, "attempts": attempts})
        return count + 1


def chop_batch_dispatch_attempts(
    routine: str, job: str, batch_id: str
) -> dict[int, int]:
    """Return persisted recovery attempt counts keyed by member index."""
    data = _read_json_object(_chop_batch_attempts_path(routine, job, batch_id))
    attempts = data.get("attempts")
    if not isinstance(attempts, dict):
        return {}
    result: dict[int, int] = {}
    for key, value in attempts.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if index >= 0 and isinstance(value, int) and not isinstance(value, bool):
            result[index] = max(0, value)
    return result


def load_chop_batch_notice_state(
    routine: str, job: str, batch_id: str
) -> dict[str, Any]:
    """Load the durable outbox state, returning an empty state when absent."""
    return _read_json_object(_chop_batch_notices_path(routine, job, batch_id))


def pending_chop_batch_notices(
    routine: str, job: str, batch_id: str
) -> list[dict[str, Any]]:
    """Return notice outbox entries that still need external delivery."""
    state = load_chop_batch_notice_state(routine, job, batch_id)
    episodes = state.get("episodes")
    if not isinstance(episodes, dict):
        return []
    pending: list[dict[str, Any]] = []
    for episode_id, episode in episodes.items():
        if not isinstance(episode, dict):
            continue
        events = episode.get("events")
        if not isinstance(events, dict):
            continue
        for event_name, event in events.items():
            if isinstance(event, dict) and not event.get("delivered"):
                pending.append(
                    {"episode_id": str(episode_id), "event": str(event_name), **event}
                )
    return pending


def update_chop_batch_notice_state(
    routine: str,
    job: str,
    batch_id: str,
    transform: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Atomically update the per-batch notice outbox sidecar."""
    path = _chop_batch_notices_path(routine, job, batch_id)
    with _locked(_mutation_lock_path(routine, job)):
        current = _read_json_object(path)
        updated = transform(dict(current))
        if not isinstance(updated, dict):
            raise ChopBatchError("notice state transform must return an object")
        updated.setdefault("schema_version", 1)
        updated.setdefault("batch_id", batch_id)
        _atomic_write_manifest(path, updated)
        return updated


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _has_pending_chop_batch_notices(routine: str, job: str, batch_id: str) -> bool:
    state = _read_json_object(_chop_batch_notices_path(routine, job, batch_id))
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


def _batch_has_dispatch_work(manifest: dict[str, Any]) -> bool:
    if _batch_is_terminal(manifest):
        return False
    members = manifest.get("members")
    return isinstance(members, list) and any(
        isinstance(member, dict)
        and str(member.get("status") or "pending") in {"pending", "dispatching"}
        for member in members
    )


def acquire_chop_batch_ownership(
    routine: str, job: str, batch_id: str, *, owner: str | None = None
) -> bool:
    """Claim executor ownership of one batch.

    Returns ``True`` when this process now owns the batch. A live owner
    (its PID still exists) keeps ownership and this returns ``False``; a
    stale record from a dead process may be superseded. Only one executor
    can own a batch, so a second routine or manual caller leaves a live
    owner alone.
    """
    ensure_chop_batches_dir(routine, job)
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    with _locked(_ownership_lock_path(routine, job)):
        current = _read_owner_record(owner_path)
        if current is not None and _pid_is_live(current.get("pid")):
            return False
        record: dict[str, Any] = {
            "batch_id": batch_id,
            "pid": os.getpid(),
            "owner": owner or f"pid:{os.getpid()}",
        }
        _atomic_write_manifest(owner_path, record)
        return True


def _release_chop_batch_ownership(routine: str, job: str, batch_id: str) -> bool:
    """Release executor ownership held by this process."""
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    with _locked(_ownership_lock_path(routine, job)):
        current = _read_owner_record(owner_path)
        if current is None:
            return False
        if current.get("pid") != os.getpid():
            return False
        try:
            owner_path.unlink()
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise ChopBatchError(
                    f"cannot release batch {batch_id!r}: {exc}"
                ) from exc
        released = True
    return released


def release_and_retire_chop_batch(routine: str, job: str, batch_id: str) -> bool:
    """Release this executor and archive the batch if its work is settled."""
    released = _release_chop_batch_ownership(routine, job, batch_id)
    if released:
        retire_chop_batch(routine, job, batch_id)
    return released


def read_chop_batch_owner(routine: str, job: str, batch_id: str) -> dict | None:
    """Return the current ownership record, if any."""
    return _read_owner_record(chop_batch_owner_path(routine, job, batch_id))


def _require_safe_batch_id(batch_id: str) -> None:
    if not batch_id or batch_id.strip() != batch_id or not batch_id.strip():
        raise ChopBatchError(f"invalid batch id {batch_id!r}")
    if "/" in batch_id or "\\" in batch_id or batch_id in {".", ".."}:
        raise ChopBatchError(f"invalid batch id {batch_id!r}")
    if len(batch_id) > 256:
        raise ChopBatchError(f"invalid batch id {batch_id!r}")


def _mutation_lock_path(routine: str, job: str) -> Path:
    return chop_batches_dir(routine, job) / CHOP_BATCH_MUTATION_LOCK_FILENAME


def _ownership_lock_path(routine: str, job: str) -> Path:
    return chop_batches_dir(routine, job) / CHOP_BATCH_OWNERSHIP_LOCK_FILENAME


def _mutex_for(key: str) -> threading.Lock:
    with _MUTEXES_LOCK:
        mutex = _MUTEXES.get(key)
        if mutex is None:
            mutex = threading.Lock()
            _MUTEXES[key] = mutex
        return mutex


class _locked:
    """Hold an in-process mutex plus an exclusive flock on a lock file."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._mutex = _mutex_for(str(lock_path))
        self._handle: Any = None

    def __enter__(self) -> _locked:
        self._mutex.acquire()
        try:
            if _writes_allowed(self._lock_path, category="axe-chop-state"):
                self._lock_path.parent.mkdir(parents=True, exist_ok=True)
                self._handle = open(self._lock_path, "a+b")  # noqa: PTH123
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            self._mutex.release()
            raise
        return self

    def __exit__(self, *exc_info: Any) -> None:
        try:
            if self._handle is not None:
                try:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                finally:
                    self._handle.close()
        finally:
            self._handle = None
            self._mutex.release()


def _atomic_write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write one manifest atomically with fsync durability."""
    if not _writes_allowed(path, category="axe-chop-state"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
        _fsync_dir(path.parent)
    except OSError as exc:
        raise ChopBatchError(f"cannot write batch file {path}: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def _fsync_dir(directory: Path) -> None:
    """Fsync a directory so creations and renames survive a crash."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _read_owner_record(path: Path) -> dict | None:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return None
        raise ChopBatchError(f"cannot read owner file {path}: {exc}") from exc
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _pid_is_live(pid: Any) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


__all__ = [
    "CHOP_BATCH_DIRNAME",
    "CHOP_BATCH_FILENAME_SUFFIX",
    "CHOP_BATCH_NOTICES_SUFFIX",
    "CHOP_BATCH_ATTEMPTS_SUFFIX",
    "CHOP_BATCH_MUTATION_LOCK_FILENAME",
    "CHOP_BATCH_OWNER_SUFFIX",
    "CHOP_BATCH_OWNERSHIP_LOCK_FILENAME",
    "MAX_PENDING_BATCHES",
    "ChopBatchCorruptError",
    "ChopBatchError",
    "ChopBatchExistsError",
    "ChopBatchNotFoundError",
    "acquire_chop_batch_ownership",
    "apply_chop_batch_event",
    "chop_batch_owner_path",
    "chop_batch_path",
    "chop_batches_dir",
    "create_chop_batch",
    "delete_chop_batch",
    "delete_archived_chop_batch",
    "chop_batch_dispatch_attempts",
    "increment_chop_batch_dispatch_attempt",
    "ensure_chop_batches_dir",
    "list_pending_chop_batches",
    "list_chop_batches_for_clan",
    "load_chop_batch",
    "load_chop_batch_notice_state",
    "pending_chop_batch_notices",
    "read_chop_batch_owner",
    "reconcile_stored_batch",
    "retire_chop_batch",
    "release_and_retire_chop_batch",
    "summarize_stored_batch",
    "update_chop_batch_notice_state",
    "update_chop_batch",
]
