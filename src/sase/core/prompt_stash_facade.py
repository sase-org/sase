"""Python facade for the Rust prompt-stash store bindings."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core.prompt_stash_wire import (
    PromptStashCursorWire,
    PromptStashEntryWire,
    PromptStashLifecycleOutcomeWire,
    PromptStashLifecycleSnapshotWire,
    PromptStashPopOutcomeWire,
    PromptStashSnapshotWire,
    prompt_stash_lifecycle_outcome_from_dict,
    prompt_stash_lifecycle_snapshot_from_dict,
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


def _checked_trash_limit(trash_limit: int) -> int:
    """Validate the trash limit before passing it to Rust.

    Rust owns limit enforcement; Python only guards the call boundary so a
    programming error fails here with a clear message instead of crossing
    the wire. User configuration never reaches this check unvalidated: read
    it through ``sase.ace.config.get_ace_prompt_stash_trash_limit``.
    """
    if type(trash_limit) is not int or trash_limit < 0:
        raise ValueError(f"trash_limit must be an integer >= 0, got {trash_limit!r}")
    return trash_limit


def read_prompt_stash_lifecycle(
    path: Path | str,
) -> PromptStashLifecycleSnapshotWire:
    """Read both stash collections through ``sase_core_rs``.

    Requires a core wheel with the trash lifecycle bindings; a stale wheel
    raises :class:`AttributeError` naming the missing binding.
    """
    payload: dict[str, Any] = _call_binding("read_prompt_stash_lifecycle", str(path))
    return prompt_stash_lifecycle_snapshot_from_dict(payload)


def trash_prompt_stash(
    path: Path | str,
    ids: Sequence[str],
    trash_limit: int,
    trashed_at: str,
) -> PromptStashLifecycleOutcomeWire:
    """Move active rows to Trash and return the lifecycle outcome.

    ``trashed_at`` is the UTC deletion time shared by the whole batch;
    ``trash_limit`` is enforced in the same Rust transaction.
    """
    payload: dict[str, Any] = _call_binding(
        "trash_prompt_stash",
        str(path),
        [str(i) for i in ids],
        _checked_trash_limit(trash_limit),
        str(trashed_at),
    )
    return prompt_stash_lifecycle_outcome_from_dict(payload)


def restore_prompt_stash(
    path: Path | str,
    ids: Sequence[str],
) -> PromptStashLifecycleOutcomeWire:
    """Move trashed rows back to Stash and return the lifecycle outcome."""
    payload: dict[str, Any] = _call_binding(
        "restore_prompt_stash", str(path), [str(i) for i in ids]
    )
    return prompt_stash_lifecycle_outcome_from_dict(payload)


def purge_prompt_stash(
    path: Path | str,
    ids: Sequence[str],
) -> PromptStashLifecycleOutcomeWire:
    """Permanently delete trashed rows and return the lifecycle outcome."""
    payload: dict[str, Any] = _call_binding(
        "purge_prompt_stash", str(path), [str(i) for i in ids]
    )
    return prompt_stash_lifecycle_outcome_from_dict(payload)


def reconcile_prompt_stash_trash(
    path: Path | str,
    trash_limit: int,
) -> PromptStashLifecycleOutcomeWire:
    """Enforce the trash limit and return the lifecycle outcome.

    The reconciliation path for a lowered configured limit: over-limit trash
    rows are permanently deleted and reported in ``evicted``, oldest first.
    """
    payload: dict[str, Any] = _call_binding(
        "reconcile_prompt_stash_trash",
        str(path),
        _checked_trash_limit(trash_limit),
    )
    return prompt_stash_lifecycle_outcome_from_dict(payload)


__all__ = [
    "PromptStashCursorWire",
    "PromptStashEntryWire",
    "PromptStashLifecycleOutcomeWire",
    "PromptStashLifecycleSnapshotWire",
    "PromptStashLockTimeoutError",
    "PromptStashPopOutcomeWire",
    "PromptStashSnapshotWire",
    "append_prompt_stash",
    "pop_prompt_stash",
    "purge_prompt_stash",
    "read_prompt_stash_lifecycle",
    "read_prompt_stash_snapshot",
    "reconcile_prompt_stash_trash",
    "restore_prompt_stash",
    "rewrite_prompt_stash",
    "set_prompt_stash_pinned",
    "trash_prompt_stash",
]
