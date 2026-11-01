"""Withdraw the published gate of a gate turn settled lost.

A lost gate turn whose bundle never reached ``complete`` (for example the
16p interruption, where the journal stuck at ``notification_prepared`` and
the record has no ``bundle_path``) still leaves a live notification and an
``available`` pending action. This helper finds the bundle by
``gate_kind``/``gate_id`` under ``interaction_requests/`` and applies the
same compensation as gate-creation failure: unregister the pending action,
dismiss the notification, and journal ``failed``. Answered gates (a
``response.json`` exists) are left alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.gate_turn.models import GateTurnRecord


def withdraw_lost_gate(record: GateTurnRecord) -> bool:
    """Withdraw the published gate of a lost gate turn, if any.

    Returns True when compensation ran, False when there was nothing to
    withdraw (no bundle, already answered, or no notification to clear).
    """
    root = _resolve_bundle_root(record)
    if root is None:
        return _withdraw_orphan_notification(record)
    if (root / "response.json").is_file():
        return False
    journal = _read_journal(root)
    notification_id: str | None = None
    if isinstance(journal, dict):
        raw = journal.get("notification_id")
        if isinstance(raw, str) and raw:
            notification_id = raw
    if notification_id is None and isinstance(record.notification_id, str):
        if record.notification_id:
            notification_id = record.notification_id
    if not notification_id:
        return False
    _compensate(root, notification_id)
    return True


def _resolve_bundle_root(record: GateTurnRecord) -> Path | None:
    if record.bundle_path:
        candidate = Path(record.bundle_path)
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            pass
    kind = (record.kind or "").strip()
    gate_id = (record.gate_id or "").strip()
    if not kind or not gate_id:
        return None
    try:
        from sase.notification_gates.paths import bundle_paths
    except Exception:
        return None
    try:
        paths = bundle_paths(kind, gate_id)
    except Exception:
        return None
    try:
        if paths.root.is_dir():
            return paths.root
    except OSError:
        return None
    return None


def _read_journal(root: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((root / ".creation.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _compensate(root: Path, notification_id: str) -> None:
    from sase.notification_gates._service_shared import write_journal
    from sase.notifications.pending_actions import unregister_notification
    from sase.notifications.store import mark_dismissed

    try:
        unregister_notification(notification_id)
    except Exception:
        pass
    try:
        mark_dismissed(notification_id)
    except Exception:
        pass
    try:
        write_journal(
            root / ".creation.json",
            state="failed",
            request_id=root.name,
            kind=root.parent.name,
            notification_id=notification_id,
        )
    except OSError:
        pass


def _withdraw_orphan_notification(record: GateTurnRecord) -> bool:
    """Best-effort withdraw when no bundle directory exists at all."""
    notification_id = record.notification_id
    if not isinstance(notification_id, str) or not notification_id:
        return False
    try:
        from sase.notifications.pending_actions import unregister_notification
        from sase.notifications.store import mark_dismissed

        try:
            unregister_notification(notification_id)
        except Exception:
            pass
        try:
            mark_dismissed(notification_id)
        except Exception:
            pass
        return True
    except Exception:
        return False


__all__ = ["withdraw_lost_gate"]
