"""Prompt history storage and retrieval for sase run commands.

The implementation is split across:

- :mod:`sase.history.prompt_store` for disk IO and mutations
- :mod:`sase.history.prompt_catalog` for read-only listing and selectors
- :mod:`sase.history.prompt_stats` for aggregate stats
- :mod:`sase.history.prompt_maintenance` for doctor/delete/prune

This module keeps the historical import and monkeypatch surface stable for the
runtime APIs. Split-module implementation details stay in their owning modules.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, cast

from sase.core.time import generate_timestamp as _generate_timestamp
from sase.history import prompt_catalog as _catalog
from sase.history import prompt_maintenance as _maintenance
from sase.history import prompt_stats as _stats
from sase.history import prompt_store as _store

PromptEntry = _store.PromptEntry
PromptHistoryRecord = _catalog.PromptHistoryRecord
PromptSelectorError = _catalog.PromptSelectorError
PromptLargest = _stats.PromptLargest
PromptHistoryStats = _stats.PromptHistoryStats
PromptStoreCorruptError = _maintenance.PromptStoreCorruptError
PromptStoreWriteError = _maintenance.PromptStoreWriteError
PromptDateError = _maintenance.PromptDateError
PromptHistoryDoctor = _maintenance.PromptHistoryDoctor
PrunePlan = _maintenance.PrunePlan

_PROMPT_HISTORY_FILE: Path | None = None
_PROMPT_PREVIEW_LENGTH = _store._PROMPT_PREVIEW_LENGTH
_MIN_PROMPT_WORDS = _store._MIN_PROMPT_WORDS
generate_timestamp = _generate_timestamp

_store_prompt_history_file = _store.prompt_history_file
_store_prompt_entry_from_json = _store.prompt_entry_from_json
_store_load_prompt_history = _store.load_prompt_history
_store_load_prompt_history_for_write = _store.load_prompt_history_for_write
_store_prompt_history_lock_file = _store.prompt_history_lock_file
_store_locked_prompt_history = _store.locked_prompt_history
_store_save_prompt_history = _store.save_prompt_history
_store_format_prompt_for_display = _store.format_prompt_for_display

_catalog_list_prompt_records = _catalog.list_prompt_records
_catalog_resolve_prompt_selector = _catalog.resolve_prompt_selector
_catalog_get_prompts_for_fzf = _catalog.get_prompts_for_fzf

_stats_compute_prompt_stats = _stats.compute_prompt_stats

_maintenance_compute_prompt_doctor = _maintenance.compute_prompt_doctor
_maintenance_delete_prompt = _maintenance.delete_prompt
_maintenance_prune_prompts = _maintenance.prune_prompts


def _sync_store_config() -> None:
    """Mirror historical module globals into the storage module."""
    _store._PROMPT_HISTORY_FILE = _PROMPT_HISTORY_FILE
    _store._PROMPT_PREVIEW_LENGTH = _PROMPT_PREVIEW_LENGTH
    _store._MIN_PROMPT_WORDS = _MIN_PROMPT_WORDS
    _store.generate_timestamp = generate_timestamp


def _sync_compat_hooks() -> None:
    """Mirror monkeypatched prompt.py storage hooks into split modules."""
    _sync_store_config()
    _store.prompt_history_file = _prompt_history_file
    _store.prompt_entry_from_json = _prompt_entry_from_json
    _store.load_prompt_history = _load_prompt_history
    cast(Any, _store.api).load_prompt_history = _load_prompt_history
    _store.load_prompt_history_for_write = _load_prompt_history_for_write
    _store.prompt_history_lock_file = _prompt_history_lock_file
    _store.locked_prompt_history = cast(Any, _locked_prompt_history)
    _store.save_prompt_history = _save_prompt_history
    _store.format_prompt_for_display = _format_prompt_for_display
    cast(Any, _store.api).format_prompt_for_display = _format_prompt_for_display


def _prompt_history_file() -> Path:
    _sync_store_config()
    return _store_prompt_history_file()


def _prompt_entry_from_json(value: object) -> PromptEntry | None:
    return _store_prompt_entry_from_json(value)


def _load_prompt_history() -> list[PromptEntry]:
    _sync_store_config()
    return _store_load_prompt_history()


def _load_prompt_history_for_write() -> list[PromptEntry]:
    _sync_store_config()
    return _store_load_prompt_history_for_write()


def _prompt_history_lock_file() -> Path:
    _sync_store_config()
    return _store_prompt_history_lock_file()


def _locked_prompt_history() -> AbstractContextManager[None]:
    _sync_store_config()
    return _store_locked_prompt_history()


def _save_prompt_history(prompts: list[PromptEntry]) -> bool:
    _sync_store_config()
    return _store_save_prompt_history(prompts)


def _format_prompt_for_display(entry: PromptEntry) -> str:
    _sync_store_config()
    return _store_format_prompt_for_display(entry)


def add_or_update_prompt(
    text: str,
    *,
    cancelled: bool = False,
    allow_short: bool = False,
) -> None:
    _sync_compat_hooks()
    return _store.add_or_update_prompt(
        text,
        cancelled=cancelled,
        allow_short=allow_short,
    )


def record_failed_launch_prompt(text: str) -> None:
    _sync_compat_hooks()
    return _store.record_failed_launch_prompt(text)


def list_prompt_records(
    *,
    include_cancelled: bool = False,
    cancelled_only: bool = False,
    query: str | None = None,
    limit: int | None = None,
) -> list[PromptHistoryRecord]:
    _sync_compat_hooks()
    return _catalog_list_prompt_records(
        include_cancelled=include_cancelled,
        cancelled_only=cancelled_only,
        query=query,
        limit=limit,
    )


def resolve_prompt_selector(
    selector: str,
    *,
    records: list[PromptHistoryRecord] | None = None,
) -> PromptHistoryRecord:
    _sync_compat_hooks()
    return _catalog_resolve_prompt_selector(selector, records=records)


def compute_prompt_stats() -> PromptHistoryStats:
    _sync_compat_hooks()
    return _stats_compute_prompt_stats()


def parse_prune_date(value: str) -> str:
    return _maintenance.parse_prune_date(value)


def compute_prompt_doctor() -> PromptHistoryDoctor:
    _sync_compat_hooks()
    return _maintenance_compute_prompt_doctor()


def delete_prompt(selector: str) -> PromptHistoryRecord:
    _sync_compat_hooks()
    return _maintenance_delete_prompt(selector)


def prune_prompts(
    *,
    keep: int | None = None,
    before: str | None = None,
    cancelled_only: bool = False,
    dry_run: bool = False,
) -> PrunePlan:
    _sync_compat_hooks()
    return _maintenance_prune_prompts(
        keep=keep,
        before=before,
        cancelled_only=cancelled_only,
        dry_run=dry_run,
    )


def get_prompts_for_fzf(
    *, include_cancelled: bool = False
) -> list[tuple[str, PromptEntry]]:
    _sync_compat_hooks()
    return _catalog_get_prompts_for_fzf(include_cancelled=include_cancelled)


__all__ = [
    "PromptDateError",
    "PromptEntry",
    "PromptHistoryDoctor",
    "PromptHistoryRecord",
    "PromptHistoryStats",
    "PromptLargest",
    "PromptSelectorError",
    "PromptStoreCorruptError",
    "PromptStoreWriteError",
    "PrunePlan",
    "add_or_update_prompt",
    "compute_prompt_doctor",
    "compute_prompt_stats",
    "delete_prompt",
    "get_prompts_for_fzf",
    "list_prompt_records",
    "parse_prune_date",
    "prune_prompts",
    "record_failed_launch_prompt",
    "resolve_prompt_selector",
]
