"""Sequence-fenced pending-ack overlay for unread acknowledgments.

Phase ``pending-ack-fence`` (epic ``sase-1d7``): snapshot reads are stamped
with a read sequence captured when the read starts, the snapshot cache
rejects stale snapshots, and in-flight acks are kept as a pending overlay
that every reconcile path honors until a post-write read retires them.

Ownership model
---------------

Each ack registers ``pending[identity] = (op_id, done_seq=None)`` before its
store worker is scheduled. When the worker succeeds, ``done_seq`` records the
current read sequence. A pending entry retires only when a snapshot whose
read-start sequence is *greater* than ``done_seq`` is applied (a read that
began after the write landed). A genuinely new completion for the same
identity therefore resurfaces at most one poll later.

A later op on the same identity overwrites the entry and takes ownership; a
failed write restores only the identities its op still owns.
"""

from __future__ import annotations

from typing import Any

#: Attribute stamped on notification snapshots carrying their read-start seq.
READ_SEQ_ATTR = "_sase_notif_read_seq"


def _get_notif_read_seq(app: Any) -> int:
    """Return the current notification read sequence (0 when never read)."""
    try:
        return int(getattr(app, "_notif_read_seq", 0) or 0)
    except (TypeError, ValueError):
        return 0


def next_notif_read_seq(app: Any) -> int:
    """Consume the next notification read sequence for a starting read."""
    seq = _get_notif_read_seq(app) + 1
    try:
        app._notif_read_seq = seq
    except (AttributeError, TypeError):
        pass
    return seq


def stamp_snapshot_read_seq(snapshot: Any, seq: int) -> Any:
    """Carry *seq* on *snapshot*; tolerate snapshots that reject attrs."""
    try:
        object.__setattr__(snapshot, READ_SEQ_ATTR, int(seq))
    except (AttributeError, TypeError, ValueError):
        try:
            setattr(snapshot, READ_SEQ_ATTR, int(seq))
        except (AttributeError, TypeError, ValueError):
            pass
    return snapshot


def snapshot_read_seq(snapshot: Any) -> int | None:
    """Return the read-start sequence carried by *snapshot*, if any."""
    try:
        seq = getattr(snapshot, READ_SEQ_ATTR, None)
    except Exception:
        return None
    if seq is None:
        return None
    try:
        return int(seq)
    except (TypeError, ValueError):
        return None


def _pending_ack_overlay_for(app: Any) -> dict[Any, tuple[int, int | None]] | None:
    """Return the app's pending-ack overlay, or ``None`` when absent."""
    overlay = getattr(app, "_pending_ack_overlay", None)
    return overlay if isinstance(overlay, dict) else None


def _ensure_pending_ack_overlay(app: Any) -> dict[Any, tuple[int, int | None]]:
    """Return the app's pending-ack overlay, creating it when possible."""
    overlay = _pending_ack_overlay_for(app)
    if overlay is not None:
        return overlay
    overlay = {}
    try:
        app._pending_ack_overlay = overlay
    except (AttributeError, TypeError):
        pass
    return overlay


def register_pending_ack(app: Any, identities: Any) -> int:
    """Register *identities* as in-flight under a fresh op id.

    A later op on the same identity overwrites the entry and takes
    ownership from any earlier op.
    """
    try:
        op_id = int(getattr(app, "_pending_ack_op_seq", 0) or 0) + 1
    except (TypeError, ValueError):
        op_id = 1
    try:
        app._pending_ack_op_seq = op_id
    except (AttributeError, TypeError):
        pass
    overlay = _ensure_pending_ack_overlay(app)
    for identity in identities:
        try:
            overlay[identity] = (op_id, None)
        except TypeError:
            continue
    return op_id


def mark_pending_ack_write_complete(
    app: Any,
    op_id: int,
    identities: Any,
) -> None:
    """Record the current read sequence as ``done_seq`` for owned entries."""
    overlay = _pending_ack_overlay_for(app)
    if overlay is None:
        return
    done_seq = _get_notif_read_seq(app)
    for identity in identities:
        try:
            entry = overlay.get(identity)
        except TypeError:
            continue
        if entry is not None and entry[0] == op_id:
            overlay[identity] = (op_id, done_seq)


def owned_pending_ack_identities(app: Any, op_id: int, identities: Any) -> set[Any]:
    """Return the subset of *identities* this op still owns."""
    overlay = _pending_ack_overlay_for(app)
    if overlay is None:
        # Apps without an overlay (older test fakes) keep legacy behavior:
        # the op owns everything it attempted.
        return set(identities)
    owned: set[Any] = set()
    for identity in identities:
        try:
            entry = overlay.get(identity)
        except TypeError:
            continue
        if entry is not None and entry[0] == op_id:
            owned.add(identity)
    return owned


def release_pending_ack_entries(app: Any, identities: Any) -> None:
    """Drop pending-ack entries, e.g. after an explicit undo restores them."""
    overlay = _pending_ack_overlay_for(app)
    if overlay is None:
        return
    for identity in identities:
        try:
            overlay.pop(identity, None)
        except TypeError:
            continue


def pending_ack_identities(app: Any) -> set[Any]:
    """Return the identities currently held in the pending-ack overlay."""
    overlay = _pending_ack_overlay_for(app)
    if overlay is None:
        return set()
    try:
        return set(overlay.keys())
    except TypeError:
        return set()


def retire_pending_ack_entries(app: Any, snapshot_seq: int | None) -> set[Any]:
    """Retire entries a post-write read has superseded; return survivors."""
    overlay = _pending_ack_overlay_for(app)
    if overlay is None or snapshot_seq is None:
        return pending_ack_identities(app)
    try:
        wanted = int(snapshot_seq)
    except (TypeError, ValueError):
        return pending_ack_identities(app)
    for identity, (_op_id, done_seq) in list(overlay.items()):
        if done_seq is not None and wanted > done_seq:
            try:
                del overlay[identity]
            except KeyError:
                continue
    return pending_ack_identities(app)


__all__ = [
    "READ_SEQ_ATTR",
    "mark_pending_ack_write_complete",
    "next_notif_read_seq",
    "owned_pending_ack_identities",
    "pending_ack_identities",
    "register_pending_ack",
    "release_pending_ack_entries",
    "retire_pending_ack_entries",
    "snapshot_read_seq",
    "stamp_snapshot_read_seq",
]
