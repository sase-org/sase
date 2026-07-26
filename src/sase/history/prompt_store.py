"""Prompt history storage primitives and public compatibility facade."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.core.paths import sase_home
from sase.core.time import generate_timestamp

_PROMPT_HISTORY_FILE: Path | None = None
_PROMPT_HISTORY_DIR: Path | None = None
_LEGACY_PROMPT_HISTORY_FILE: Path | None = None
_UNKNOWN_SHARD_KEY = "unknown"

# Display settings for fzf
_PROMPT_PREVIEW_LENGTH = 60

# Skip prompts shorter than this. Sub-five-word scraps are usually too terse to
# be useful to re-run from history and mostly clutter the store.
_MIN_PROMPT_WORDS = 5


@dataclass
class PromptEntry:
    """A single prompt history entry."""

    text: str
    timestamp: str
    last_used: str
    cancelled: bool = False
    # Legacy fields loaded from old history files for transitional UI
    # compatibility. New writes intentionally omit them.
    branch_or_workspace: str = ""
    workspace: str = ""


class PromptHistoryLoadError(Exception):
    """Raised when prompt history cannot be loaded for a safe mutation."""


def is_recordable_prompt(text: str, *, allow_short: bool = False) -> bool:
    """Return True if *text* meets the prompt-history recording threshold."""
    return allow_short or len(text.split()) >= _MIN_PROMPT_WORDS


def prompt_history_file() -> Path:
    """Return the legacy single-file prompt-history path.

    Kept for migration, diagnostics, and tests that need to seed a pre-shard
    store. New prompt-history writes use :func:`prompt_history_dir`.
    """
    return legacy_prompt_history_file()


def legacy_prompt_history_file() -> Path:
    """Return the legacy single-file prompt-history path."""
    return (
        _LEGACY_PROMPT_HISTORY_FILE
        or _PROMPT_HISTORY_FILE
        or sase_home() / "prompt_history.json"
    )


def prompt_history_dir() -> Path:
    """Return the sharded prompt-history directory."""
    if _PROMPT_HISTORY_DIR is not None:
        return _PROMPT_HISTORY_DIR
    if _PROMPT_HISTORY_FILE is not None:
        return _PROMPT_HISTORY_FILE.with_suffix("")
    legacy_file = legacy_prompt_history_file()
    return legacy_file.with_suffix("")


def shard_key_for_timestamp(ts: str) -> str:
    """Return the ``YYMM`` shard key for a SASE timestamp, or ``unknown``."""
    raw = ts.strip()
    try:
        datetime.strptime(raw, "%y%m%d_%H%M%S")
    except ValueError:
        return _UNKNOWN_SHARD_KEY
    return raw[:4]


def shard_path(key: str) -> Path:
    """Return the JSON path for a shard key."""
    return prompt_history_dir() / f"{key}.json"


def _shard_sort_key(path: Path) -> tuple[int, str]:
    """Sort valid YYMM shards before unknown, newest first."""
    key = path.stem
    if len(key) == 4 and key.isdigit():
        return (1, key)
    if key == _UNKNOWN_SHARD_KEY:
        return (0, key)
    return (-1, key)


def iter_shard_paths_newest_first() -> Iterator[Path]:
    """Yield shard files newest first, with ``unknown`` last."""
    history_dir = prompt_history_dir()
    if not history_dir.exists() or not history_dir.is_dir():
        return
    paths = [
        path
        for path in history_dir.glob("*.json")
        if path.is_file() and (path.stem == _UNKNOWN_SHARD_KEY or path.stem.isdigit())
    ]
    yield from sorted(paths, key=_shard_sort_key, reverse=True)


def prompt_entry_from_json(value: object) -> PromptEntry | None:
    """Convert a raw JSON prompt entry into a PromptEntry."""
    if not isinstance(value, dict):
        return None

    text = value.get("text")
    timestamp = value.get("timestamp")
    last_used = value.get("last_used")
    if (
        not isinstance(text, str)
        or not isinstance(timestamp, str)
        or not isinstance(last_used, str)
    ):
        return None

    branch_or_workspace = value.get("branch_or_workspace", "")
    workspace = value.get("workspace", "")
    cancelled = value.get("cancelled", False)
    return PromptEntry(
        text=text,
        timestamp=timestamp,
        last_used=last_used,
        cancelled=cancelled if isinstance(cancelled, bool) else False,
        branch_or_workspace=(
            branch_or_workspace if isinstance(branch_or_workspace, str) else ""
        ),
        workspace=workspace if isinstance(workspace, str) else "",
    )


def _entries_from_data(data: object) -> list[PromptEntry]:
    if not isinstance(data, dict):
        return []
    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        return []
    return [
        entry
        for entry in (prompt_entry_from_json(prompt) for prompt in prompts)
        if entry is not None
    ]


def _entries_from_data_for_write(data: object) -> list[PromptEntry]:
    if not isinstance(data, dict):
        raise PromptHistoryLoadError
    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        raise PromptHistoryLoadError
    return [
        entry
        for entry in (prompt_entry_from_json(prompt) for prompt in prompts)
        if entry is not None
    ]


def _load_legacy_prompt_history() -> list[PromptEntry]:
    history_file = legacy_prompt_history_file()
    if not history_file.exists():
        return []

    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return _entries_from_data(data)


def load_legacy_prompt_history_for_write() -> list[PromptEntry]:
    """Load the legacy store without masking corrupt or partial data."""
    history_file = legacy_prompt_history_file()
    if not history_file.exists():
        return []

    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)
        return _entries_from_data_for_write(data)
    except (AttributeError, OSError, json.JSONDecodeError, KeyError) as exc:
        raise PromptHistoryLoadError from exc


def load_shard(path: Path) -> list[PromptEntry]:
    """Load one prompt-history shard, masking corrupt shards for read-only use."""
    if not path.exists():
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return _entries_from_data(data)


def load_shard_for_write(path: Path) -> list[PromptEntry]:
    """Load one shard for mutation without masking corrupt/partial files."""
    if not path.exists():
        return []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return _entries_from_data_for_write(data)
    except (AttributeError, OSError, json.JSONDecodeError, KeyError) as exc:
        raise PromptHistoryLoadError from exc


def _prompt_to_json(entry: PromptEntry) -> dict[str, object]:
    data: dict[str, object] = {
        "text": entry.text,
        "timestamp": entry.timestamp,
        "last_used": entry.last_used,
        "cancelled": entry.cancelled,
    }
    if entry.branch_or_workspace:
        data["branch_or_workspace"] = entry.branch_or_workspace
    if entry.workspace:
        data["workspace"] = entry.workspace
    return data


def save_shard(path: Path, prompts: list[PromptEntry]) -> bool:
    """Atomically save one prompt-history shard."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"prompts": [_prompt_to_json(p) for p in prompts]}
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=f".{os.getpid()}.tmp",
            dir=path.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        except OSError:
            try:
                temp_path.unlink()
            except OSError:
                pass
            return False
        return True
    except OSError:
        return False


def _entry_last_used_sort_key(entry: PromptEntry) -> str:
    return entry.last_used


def _reconcile_duplicate_prompt(
    current: PromptEntry,
    duplicate: PromptEntry,
) -> PromptEntry:
    """Merge duplicate prompt entries while keeping newest usage authoritative."""
    if duplicate.timestamp < current.timestamp:
        current.timestamp = duplicate.timestamp
    return current


def dedup_prompt_entries_newest_first(
    entries: Iterator[PromptEntry],
) -> list[PromptEntry]:
    """Deduplicate newest-first entries while preserving the earliest creation."""
    by_text: OrderedDict[str, PromptEntry] = OrderedDict()
    for entry in entries:
        existing = by_text.get(entry.text)
        if existing is None:
            by_text[entry.text] = PromptEntry(
                text=entry.text,
                timestamp=entry.timestamp,
                last_used=entry.last_used,
                cancelled=entry.cancelled,
                branch_or_workspace=entry.branch_or_workspace,
                workspace=entry.workspace,
            )
            continue
        _reconcile_duplicate_prompt(existing, entry)
    return list(by_text.values())


def _iter_all_shard_entries_newest_first() -> Iterator[PromptEntry]:
    for path in iter_shard_paths_newest_first():
        entries = load_shard(path)
        entries.sort(key=_entry_last_used_sort_key, reverse=True)
        yield from entries


def load_all_prompt_history() -> list[PromptEntry]:
    """Load and dedup prompt history from every shard, newest first."""
    try:
        ensure_migrated_for_read()
    except PromptHistoryLoadError:
        return dedup_prompt_entries_newest_first(
            iter(
                sorted(
                    _load_legacy_prompt_history(),
                    key=_entry_last_used_sort_key,
                    reverse=True,
                )
            )
        )
    return dedup_prompt_entries_newest_first(_iter_all_shard_entries_newest_first())


def load_prompt_history() -> list[PromptEntry]:
    """Load prompt history from disk.

    Returns:
        Deduped PromptEntry objects, or an empty list if no store exists.
    """
    return load_all_prompt_history()


def load_prompt_history_for_write() -> list[PromptEntry]:
    """Load all shards for a writer without masking corrupt/partial files."""
    ensure_migrated()
    entries: list[PromptEntry] = []
    for path in iter_shard_paths_newest_first():
        shard_entries = load_shard_for_write(path)
        shard_entries.sort(key=_entry_last_used_sort_key, reverse=True)
        entries.extend(shard_entries)
    return dedup_prompt_entries_newest_first(iter(entries))


def _prompt_history_lock_file() -> Path:
    """Return the lock file path for prompt history mutations."""
    return legacy_prompt_history_file().with_name("prompt_history.lock")


@contextmanager
def locked_prompt_history() -> Iterator[None]:
    """Hold an exclusive lock for prompt-history read/modify/write cycles."""
    lock_file = _prompt_history_lock_file()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def save_prompt_history(prompts: list[PromptEntry]) -> bool:
    """Save prompt history to monthly shards.

    Args:
        prompts: List of PromptEntry objects to save.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        ensure_migrated()
        history_dir = prompt_history_dir()
        history_dir.mkdir(parents=True, exist_ok=True)
        buckets: dict[str, list[PromptEntry]] = {}
        for prompt in prompts:
            key = shard_key_for_timestamp(prompt.last_used)
            buckets.setdefault(key, []).append(prompt)

        existing_paths = set(iter_shard_paths_newest_first())
        target_paths = {shard_path(key) for key in buckets}
        for path in existing_paths - target_paths:
            try:
                path.unlink()
            except OSError:
                return False

        for key, shard_prompts in buckets.items():
            shard_prompts.sort(key=_entry_last_used_sort_key, reverse=True)
            if not save_shard(shard_path(key), shard_prompts):
                return False
        return True
    except (OSError, PromptHistoryLoadError):
        return False


def format_prompt_for_display(entry: PromptEntry) -> str:
    """Format a prompt entry for fzf display.

    Args:
        entry: The prompt entry to format.

    Returns:
        Formatted display string.
    """
    # Format prompt text: replace newlines with spaces, truncate if needed
    from sase.project_display_names import humanize_vcs_refs_in_text

    preview = (
        humanize_vcs_refs_in_text(entry.text).replace("\n", " ").replace("\r", " ")
    )
    if len(preview) > _PROMPT_PREVIEW_LENGTH:
        preview = preview[:_PROMPT_PREVIEW_LENGTH] + "..."

    return f"{entry.last_used} | {preview}"


# These imports intentionally come last: the extracted modules call storage
# primitives through this facade so existing path and IO patch points keep
# working for callers and tests.
from sase.history.prompt_store_migration import (  # noqa: E402
    ensure_migrated,
    ensure_migrated_for_read,
)
from sase.history.prompt_store_mutations import (  # noqa: E402
    add_or_update_prompt,
    record_failed_launch_prompt,
    rewrite_prompt_text_exact,
)
