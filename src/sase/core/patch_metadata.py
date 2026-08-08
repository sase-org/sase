"""Compatibility helpers for Patch/stitch metadata keys."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def canonicalize_patch_metadata(payload: MutableMapping[str, Any]) -> None:
    """Populate canonical Patch metadata keys and stable legacy aliases.

    Serialized marker files still carry legacy keys for installed readers. In
    memory, callers can use canonical ``patch_name`` / ``stitch_id`` while old
    ``changespec_name`` / ``cl_name`` / ``commit_entry_id`` / ``entry_id`` reads keep
    working.
    """
    patch_name = _first_text(
        payload.get("patch_name"),
        payload.get("changespec_name"),
        payload.get("cl_name"),
    )
    if patch_name:
        payload.setdefault("patch_name", patch_name)
        payload.setdefault("changespec_name", patch_name)
        payload.setdefault("cl_name", patch_name)

    commit_patch_name = _first_text(
        payload.get("commit_patch_name"),
        payload.get("commit_changespec_name"),
    )
    if commit_patch_name:
        payload.setdefault("commit_patch_name", commit_patch_name)
        payload.setdefault("commit_changespec_name", commit_patch_name)

    stitch_id = _first_text(
        payload.get("stitch_id"),
        payload.get("commit_entry_id"),
        payload.get("entry_id"),
    )
    if stitch_id:
        payload.setdefault("stitch_id", stitch_id)
        payload.setdefault("commit_entry_id", stitch_id)
        payload.setdefault("entry_id", stitch_id)


__all__ = ["canonicalize_patch_metadata"]
