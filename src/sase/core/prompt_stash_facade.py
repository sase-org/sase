"""Python facade for the Rust prompt-stash store bindings."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from sase.core.prompt_stash_wire import (
    PromptStashEntryWire,
    PromptStashPopOutcomeWire,
    PromptStashSnapshotWire,
    prompt_stash_pop_outcome_from_dict,
    prompt_stash_snapshot_from_dict,
    prompt_stash_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding


def read_prompt_stash_snapshot(path: Path | str) -> PromptStashSnapshotWire:
    """Read prompt-stash rows through ``sase_core_rs`` and rehydrate wires."""
    binding = require_rust_binding("read_prompt_stash_snapshot")
    payload: dict[str, Any] = binding(str(path))
    return prompt_stash_snapshot_from_dict(payload)


def append_prompt_stash(
    path: Path | str,
    entry: PromptStashEntryWire | dict[str, Any],
) -> PromptStashSnapshotWire:
    """Append one stash entry through Rust and return the updated snapshot."""
    binding = require_rust_binding("append_prompt_stash")
    payload: dict[str, Any] = binding(
        str(path), prompt_stash_wire_to_json_dict(entry)
    )
    return prompt_stash_snapshot_from_dict(payload)


def pop_prompt_stash(
    path: Path | str,
    ids: Sequence[str],
) -> PromptStashPopOutcomeWire:
    """Remove entries with the given ids and return removed rows + snapshot."""
    binding = require_rust_binding("pop_prompt_stash")
    payload: dict[str, Any] = binding(str(path), [str(i) for i in ids])
    return prompt_stash_pop_outcome_from_dict(payload)


def rewrite_prompt_stash(
    path: Path | str,
    entries: Iterable[PromptStashEntryWire] | Iterable[dict[str, Any]],
) -> PromptStashSnapshotWire:
    """Rewrite the store through Rust's lock/tempfile/rename path (merge)."""
    binding = require_rust_binding("rewrite_prompt_stash")
    payload: dict[str, Any] = binding(
        str(path), prompt_stash_wire_to_json_dict(list(entries))
    )
    return prompt_stash_snapshot_from_dict(payload)


__all__ = [
    "PromptStashEntryWire",
    "PromptStashPopOutcomeWire",
    "PromptStashSnapshotWire",
    "append_prompt_stash",
    "pop_prompt_stash",
    "read_prompt_stash_snapshot",
    "rewrite_prompt_stash",
]
