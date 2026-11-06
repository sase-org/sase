"""Bounded tracking for recovery settlements awaiting projection repair."""

from __future__ import annotations

import json
import logging
from pathlib import Path

LOG = logging.getLogger(__name__)

_PENDING_REPAIRS_FILENAME = "pending_recovery_repairs.json"
_PENDING_REPAIRS_LIMIT = 50


def _pending_repairs_path() -> Path:
    from sase.core.paths import sase_subdir
    from sase.agent.hijack.ledger import LEDGER_DIRNAME

    return sase_subdir(LEDGER_DIRNAME) / _PENDING_REPAIRS_FILENAME


def _pending_lock_path() -> Path:
    return _pending_repairs_path().with_suffix(".json.lock")


def read_pending_repairs() -> list[str]:
    try:
        from sase.notification_gates.durability import file_lock

        path = _pending_repairs_path()
        try:
            with file_lock(_pending_lock_path(), timeout=5.0):
                payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    seen: list[str] = []
    for entry in payload:
        if isinstance(entry, str) and entry and entry not in seen:
            seen.append(entry)
    return seen[:_PENDING_REPAIRS_LIMIT]


def add_pending_repair(hijack_id: str) -> None:
    if not hijack_id:
        return
    try:
        from sase.notification_gates.durability import atomic_write_json, file_lock

        path = _pending_repairs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(_pending_lock_path(), timeout=10.0):
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = []
            pending: list[str] = []
            if isinstance(current, list):
                for entry in current:
                    if isinstance(entry, str) and entry and entry not in pending:
                        pending.append(entry)
            if hijack_id not in pending:
                pending.append(hijack_id)
            atomic_write_json(path, pending[-_PENDING_REPAIRS_LIMIT:])
    except OSError:
        LOG.warning("could not track pending recovery repair", exc_info=True)
    except Exception:
        LOG.warning("could not track pending recovery repair", exc_info=True)


def clear_pending_repair(hijack_id: str) -> None:
    if not hijack_id:
        return
    try:
        from sase.notification_gates.durability import atomic_write_json, file_lock

        path = _pending_repairs_path()
        with file_lock(_pending_lock_path(), timeout=10.0):
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            if not isinstance(current, list):
                return
            pending = [entry for entry in current if entry != hijack_id]
            atomic_write_json(path, pending)
    except OSError:
        pass
    except Exception:
        pass
