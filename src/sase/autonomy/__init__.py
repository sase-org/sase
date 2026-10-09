"""Core-owned ``%auto`` autonomy record adapter (``%auto`` E1)."""

from __future__ import annotations

from sase.autonomy.record import (
    LEGACY_AUTONOMY_KEYS,
    apply_record_meta_patch,
    auto_applies,
    autonomy_inherit_record,
    evaluate,
    legacy_projection,
    live_record,
    mutate_record,
    read_record,
    record_meta_patch,
    record_only,
    refresh_record_from_legacy,
    resolve_selection,
    RETUNE_DROP_KEYS,
    RETUNE_TRIGGER_KEYS,
    retune_meta_record,
    selection_to_prompt_prefix,
    with_legacy_projection,
)

__all__ = [
    "LEGACY_AUTONOMY_KEYS",
    "apply_record_meta_patch",
    "auto_applies",
    "autonomy_inherit_record",
    "evaluate",
    "legacy_projection",
    "live_record",
    "mutate_record",
    "read_record",
    "record_meta_patch",
    "record_only",
    "refresh_record_from_legacy",
    "resolve_selection",
    "RETUNE_DROP_KEYS",
    "RETUNE_TRIGGER_KEYS",
    "retune_meta_record",
    "selection_to_prompt_prefix",
    "with_legacy_projection",
]
