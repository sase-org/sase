"""Generation-fenced pending-ack overlay for unread acknowledgments.

Phase ``core-unread-ack-index`` (epic ``sase-1d7``): the notification
store persists a generation that bumps on every successful write. An ack
returns the generation its write landed in, and snapshots carry the
generation their rows were observed at. In-flight acks are kept as a
pending overlay that every reconcile path honors until an applied index
generation at or past the ack's generation retires them.

Ownership model
---------------

Each ack registers ``pending[identity] = (op_id, done_generation=None)``
before its store worker is scheduled. When the worker succeeds,
``done_generation`` records the generation ``ack_agent_completions``
returned. A pending entry retires only when an applied generation is
**greater than or equal to** ``done_generation`` (the ack's returned
generation already includes its write). A genuinely new completion for
the same identity therefore resurfaces at most one poll later.

A later op on the same identity overwrites the entry and takes
ownership; a failed write restores only the identities its op still
owns.
"""

from __future__ import annotations

from typing import Any


def snapshot_generation(snapshot: Any) -> int | None:
    """Return the store generation carried by *snapshot*, if any.

    Reads the wire field ``generation``. Snapshots without one (test
    doubles, locally derived snapshots) report ``None`` and inherit the
    cached generation wherever they are applied.
    """
    try:
        generation = getattr(snapshot, "generation", None)
    except Exception:
        return None
    if generation is None:
        return None
    try:
        return int(generation)
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
    generation: int | None,
) -> None:
    """Record the ack's returned store generation for owned entries."""
    overlay = _pending_ack_overlay_for(app)
    if overlay is None:
        return
    try:
        done_generation = int(generation) if generation is not None else None
    except (TypeError, ValueError):
        done_generation = None
    for identity in identities:
        try:
            entry = overlay.get(identity)
        except TypeError:
            continue
        if entry is not None and entry[0] == op_id:
            overlay[identity] = (op_id, done_generation)


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


def retire_pending_ack_entries(app: Any, applied_generation: int | None) -> set[Any]:
    """Retire entries an applied generation has superseded; return survivors."""
    overlay = _pending_ack_overlay_for(app)
    if overlay is None or applied_generation is None:
        return pending_ack_identities(app)
    try:
        wanted = int(applied_generation)
    except (TypeError, ValueError):
        return pending_ack_identities(app)
    for identity, (_op_id, done_generation) in list(overlay.items()):
        if done_generation is not None and wanted >= done_generation:
            try:
                del overlay[identity]
            except KeyError:
                continue
    return pending_ack_identities(app)


__all__ = [
    "mark_pending_ack_write_complete",
    "owned_pending_ack_identities",
    "pending_ack_identities",
    "register_pending_ack",
    "release_pending_ack_entries",
    "retire_pending_ack_entries",
    "snapshot_generation",
]
