"""Python facade for the Rust prompt-stash store bindings."""

from __future__ import annotations

from collections.abc import Sequence
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


class PromptStashLockTimeoutError(TimeoutError):
    """The shared prompt-stash lock stayed busy past the bounded wait."""


def _call_binding(name: str, *args: Any) -> Any:
    binding = require_rust_binding(name)
    try:
        return binding(*args)
    except Exception as exc:
        if isinstance(exc, TimeoutError) or (
            type(exc).__name__ == "PromptStashLockTimeoutError"
        ):
            raise PromptStashLockTimeoutError(str(exc)) from exc
        raise


def read_prompt_stash_snapshot(path: Path | str) -> PromptStashSnapshotWire:
    """Read prompt-stash rows through ``sase_core_rs`` and rehydrate wires."""
    payload: dict[str, Any] = _call_binding("read_prompt_stash_snapshot", str(path))
    return prompt_stash_snapshot_from_dict(payload)


def append_prompt_stash(
    path: Path | str,
    entry: PromptStashEntryWire | dict[str, Any],
) -> PromptStashSnapshotWire:
    """Append one stash entry through Rust and return the updated snapshot."""
    payload: dict[str, Any] = _call_binding(
        "append_prompt_stash", str(path), prompt_stash_wire_to_json_dict(entry)
    )
    return prompt_stash_snapshot_from_dict(payload)


def pop_prompt_stash(
    path: Path | str,
    ids: Sequence[str],
) -> PromptStashPopOutcomeWire:
    """Remove entries with the given ids and return removed rows + snapshot."""
    payload: dict[str, Any] = _call_binding(
        "pop_prompt_stash", str(path), [str(i) for i in ids]
    )
    return prompt_stash_pop_outcome_from_dict(payload)


def set_prompt_stash_pinned(
    path: Path | str,
    ids: Sequence[str],
    pinned: bool,
) -> PromptStashSnapshotWire:
    """Set the persisted pin flag for the given entry ids."""
    payload: dict[str, Any] = _call_binding(
        "set_prompt_stash_pinned",
        str(path),
        [str(i) for i in ids],
        bool(pinned),
    )
    return prompt_stash_snapshot_from_dict(payload)


def rewrite_prompt_stash(
    path: Path | str,
    entries: Sequence[PromptStashEntryWire | dict[str, Any]],
) -> PromptStashSnapshotWire:
    """Rewrite stash rows by id through Rust and return the updated snapshot."""
    payload: dict[str, Any] = _call_binding(
        "rewrite_prompt_stash",
        str(path),
        prompt_stash_wire_to_json_dict(entries),
    )
    return prompt_stash_snapshot_from_dict(payload)


__all__ = [
    "PromptStashEntryWire",
    "PromptStashLockTimeoutError",
    "PromptStashPopOutcomeWire",
    "PromptStashSnapshotWire",
    "append_prompt_stash",
    "pop_prompt_stash",
    "read_prompt_stash_snapshot",
    "rewrite_prompt_stash",
    "set_prompt_stash_pinned",
]
