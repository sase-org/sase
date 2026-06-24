"""Prompt history storage and retrieval for sase run commands.

This module is a thin compatibility facade. The implementation is split across:

- :mod:`sase.history.prompt_store` for disk IO and mutations
- :mod:`sase.history.prompt_catalog` for read-only listing and selectors
- :mod:`sase.history.prompt_stats` for aggregate stats
- :mod:`sase.history.prompt_maintenance` for doctor/delete/prune

It re-exports only the public command/runtime API so existing callers can keep
importing prompt-history behavior from ``sase.history.prompt``. Storage
internals live in (and should be imported from) their owning modules.
"""

from __future__ import annotations

from sase.history.prompt_catalog import (
    PromptHistoryPage,
    PromptHistoryPageCursor,
    PromptHistoryRecord,
    PromptSelectorError,
    get_prompts_for_fzf,
    load_prompt_record_page,
    list_prompt_records,
    resolve_prompt_selector,
)
from sase.history.prompt_maintenance import (
    PromptDateError,
    PromptHistoryDoctor,
    PromptStoreCorruptError,
    PromptStoreWriteError,
    PrunePlan,
    compute_prompt_doctor,
    delete_prompt,
    parse_prune_date,
    prune_prompts,
)
from sase.history.prompt_stats import (
    PromptHistoryStats,
    PromptLargest,
    compute_prompt_stats,
)
from sase.history.prompt_store import (
    PromptEntry,
    add_or_update_prompt,
    is_recordable_prompt,
    load_prompt_history,
    prompt_history_file,
    record_failed_launch_prompt,
    save_prompt_history,
    shard_key_for_timestamp,
    shard_path,
)

__all__ = [
    "PromptDateError",
    "PromptEntry",
    "PromptHistoryDoctor",
    "PromptHistoryPage",
    "PromptHistoryPageCursor",
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
    "is_recordable_prompt",
    "load_prompt_history",
    "load_prompt_record_page",
    "list_prompt_records",
    "parse_prune_date",
    "prompt_history_file",
    "prune_prompts",
    "record_failed_launch_prompt",
    "resolve_prompt_selector",
    "save_prompt_history",
    "shard_key_for_timestamp",
    "shard_path",
]
