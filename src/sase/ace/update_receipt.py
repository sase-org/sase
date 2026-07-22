"""One-shot post-update toast handoff for ACE restarts.

This public facade keeps receipt construction, data types, and persistence in
one stable import location while their implementations live in focused helper
modules. The state remains presentation-only: the old ACE process writes a
receipt before re-execing, and the new process consumes it after first paint.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

from sase.ace._update_receipt_builders import build_update_receipt
from sase.ace._update_receipt_codec import receipt_from_json, receipt_to_json
from sase.ace._update_receipt_models import (
    ProviderUpdateReceiptResult,
    RepoCommitGroup,
    UpdateToastReceipt,
    UpdateVersionTransition,
)
from sase.core.paths import sase_home

log = logging.getLogger(__name__)

_FRESHNESS_SECONDS = 30 * 60

# Test override for the backing file. ``None`` falls back to the per-user path
# under ``sase_home()``, matching the small-state helpers in this package.
_PENDING_UPDATE_TOAST_FILE: Path | None = None

# Backward-compatible private name used by existing tests and receipt fixtures.
_ProviderUpdateReceiptResult = ProviderUpdateReceiptResult


def write_pending_update_toast(receipt: UpdateToastReceipt) -> bool:
    """Atomically persist *receipt* for the next ACE process, best-effort."""
    path = _pending_update_toast_file()
    tmp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=f".{os.getpid()}.tmp",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(receipt_to_json(receipt), tmp, sort_keys=True)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
        return True
    except OSError:
        log.debug("Failed to persist pending update toast", exc_info=True)
        if tmp_path is not None:
            _safe_unlink(tmp_path)
        return False


def read_and_clear_pending_update_toast(
    *, now: float | None = None
) -> UpdateToastReceipt | None:
    """Read and delete the pending update toast receipt, if one is valid."""
    path = _pending_update_toast_file()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        log.debug("Failed to read pending update toast", exc_info=True)
        _safe_unlink(path)
        return None

    _safe_unlink(path)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        log.debug("Ignoring malformed pending update toast", exc_info=True)
        return None

    receipt = receipt_from_json(payload)
    if receipt is None:
        return None
    current = time.time() if now is None else float(now)
    if abs(current - receipt.created_at) > _FRESHNESS_SECONDS:
        return None
    return receipt


def _pending_update_toast_file() -> Path:
    return _PENDING_UPDATE_TOAST_FILE or sase_home() / "pending_update_toast.json"


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.debug("Failed to remove pending update toast file", exc_info=True)


__all__ = [
    "UpdateToastReceipt",
    "UpdateVersionTransition",
    "RepoCommitGroup",
    "build_update_receipt",
    "read_and_clear_pending_update_toast",
    "write_pending_update_toast",
]
