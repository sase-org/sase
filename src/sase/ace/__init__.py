"""Ace subcommand for iterating through Patches."""

import sys
from pathlib import Path

from .patch import Stitch

PENDING_UPDATE_TOAST_FILENAME = "pending_update_toast.json"
_PENDING_UPDATE_TOAST_FILE: Path | None = None


def pending_update_toast_file() -> Path:
    """Return the update-toast path without importing its receipt implementation."""
    override = _PENDING_UPDATE_TOAST_FILE
    receipt_module = sys.modules.get("sase.ace.update_receipt")
    if override is None and receipt_module is not None:
        candidate = getattr(receipt_module, "_PENDING_UPDATE_TOAST_FILE", None)
        if isinstance(candidate, Path):
            override = candidate
    if override is None:
        from sase.core.paths import sase_home

        override = sase_home() / PENDING_UPDATE_TOAST_FILENAME
    return override


__all__ = ["PENDING_UPDATE_TOAST_FILENAME", "Stitch", "pending_update_toast_file"]
