"""Shared metadata and numeric conversions for typed chop admission."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

AXE_CHOP_SOURCE_SURFACE = "axe_chop"
UNIT_DISPATCH_METADATA_KEY = "unit_dispatch_metadata"


def unit_metadata(data: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = data.get(UNIT_DISPATCH_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and key and isinstance(value, Mapping):
            result[key] = value
    return result


def int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def chop_batch_cancelled_for_typed_request(data: Mapping[str, Any]) -> bool:
    """Return whether the outer durable batch cancelled this typed request."""
    metadata = unit_metadata(data)
    first = next(iter(metadata.values()), None)
    if first is None:
        return False
    routine = str(first.get("lumberjack_name") or "")
    job = str(first.get("chop_name") or "")
    batch_id = str(first.get("run_id") or "")
    if not routine or not job or not batch_id:
        return False

    return chop_batch_is_cancelled(routine, job, batch_id)


def chop_batch_is_cancelled(routine: str, job: str, batch_id: str) -> bool:
    """Fail closed when outer chop state cannot rule out cancellation."""
    if not routine or not job or not batch_id:
        return False

    from . import chop_batch_store

    try:
        manifest = chop_batch_store.load_chop_batch(routine, job, batch_id)
    except chop_batch_store.ChopBatchNotFoundError:
        return False
    except chop_batch_store.ChopBatchError:
        return True
    return str(manifest.get("status") or "") == "cancelled"
