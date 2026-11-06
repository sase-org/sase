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


def read_pending_repairs() -> list[str]:
    try:
        payload = json.loads(_pending_repairs_path().read_text(encoding="utf-8"))
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
    pending = read_pending_repairs()
    if hijack_id not in pending:
        pending.append(hijack_id)
    try:
        _pending_repairs_path().parent.mkdir(parents=True, exist_ok=True)
        _pending_repairs_path().write_text(
            json.dumps(pending[-_PENDING_REPAIRS_LIMIT:]), encoding="utf-8"
        )
    except OSError:
        LOG.warning("could not track pending recovery repair", exc_info=True)


def clear_pending_repair(hijack_id: str) -> None:
    if not hijack_id:
        return
    pending = [entry for entry in read_pending_repairs() if entry != hijack_id]
    try:
        _pending_repairs_path().write_text(json.dumps(pending), encoding="utf-8")
    except OSError:
        pass
