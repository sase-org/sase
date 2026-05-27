"""Hook command history storage and retrieval."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sase.core.paths import sase_home
from sase.core.time import generate_timestamp

_HOOK_HISTORY_FILE: Path | None = None


@dataclass
class HookHistoryEntry:
    """A single hook history entry."""

    command: str  # The hook command
    timestamp: str  # When first created (YYMMDD_HHMMSS)
    last_used: str  # When last used


def _hook_history_file() -> Path:
    return _HOOK_HISTORY_FILE or sase_home() / "hook_history.json"


def _load_hook_history() -> list[HookHistoryEntry]:
    """Load hook history from disk.

    Returns:
        List of HookHistoryEntry objects, or empty list if file doesn't exist.
    """
    history_file = _hook_history_file()
    if not history_file.exists():
        return []

    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)

        hooks = data.get("hooks", [])
        return [
            HookHistoryEntry(
                command=h["command"],
                timestamp=h["timestamp"],
                last_used=h["last_used"],
            )
            for h in hooks
            if isinstance(h, dict)
            and "command" in h
            and "timestamp" in h
            and "last_used" in h
        ]
    except (OSError, json.JSONDecodeError, KeyError):
        return []


def _save_hook_history(hooks: list[HookHistoryEntry]) -> bool:
    """Save hook history to disk.

    Args:
        hooks: List of HookHistoryEntry objects to save.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        history_file = _hook_history_file()
        history_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"hooks": [asdict(h) for h in hooks]}
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError:
        return False


def add_or_update_hook(command: str) -> None:
    """Add a new hook or update an existing hook's last_used timestamp.

    Deduplication key is the command string. If a matching entry exists,
    it is deleted and replaced with a new entry at the end (most recent).

    Args:
        command: The hook command string.
    """
    hooks = _load_hook_history()
    current_timestamp = generate_timestamp()

    # Remove existing entry with same command
    hooks = [h for h in hooks if h.command != command]

    # Add new entry at the end
    new_entry = HookHistoryEntry(
        command=command,
        timestamp=current_timestamp,
        last_used=current_timestamp,
    )
    hooks.append(new_entry)
    _save_hook_history(hooks)


def delete_hook(command: str) -> bool:
    """Delete a hook from history by command string.

    Args:
        command: The hook command to delete.

    Returns:
        True if deletion was successful (or command didn't exist).
    """
    hooks = _load_hook_history()
    original_len = len(hooks)
    hooks = [h for h in hooks if h.command != command]
    if len(hooks) < original_len:
        return _save_hook_history(hooks)
    return True


def get_hooks_for_display() -> list[HookHistoryEntry]:
    """Get hooks sorted by last_used descending (most recent first).

    Returns:
        List of HookHistoryEntry objects sorted for display.
    """
    hooks = _load_hook_history()
    hooks.sort(key=lambda h: h.last_used, reverse=True)
    return hooks
