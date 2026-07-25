"""Low-level prompt history storage and mutation helpers."""

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


@dataclass(frozen=True)
class _PromptMutation:
    """A prompt history mutation to apply under the writer lock."""

    text: str
    cancelled: bool
    force_cancelled: bool = False


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


def _load_legacy_prompt_history_for_write() -> list[PromptEntry]:
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


def _dedup_entries_newest_first(entries: Iterator[PromptEntry]) -> list[PromptEntry]:
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
        return _dedup_entries_newest_first(
            iter(
                sorted(
                    _load_legacy_prompt_history(),
                    key=_entry_last_used_sort_key,
                    reverse=True,
                )
            )
        )
    return _dedup_entries_newest_first(_iter_all_shard_entries_newest_first())


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
    return _dedup_entries_newest_first(iter(entries))


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


def _raw_prompt_count(path: Path) -> int:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise PromptHistoryLoadError
    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        raise PromptHistoryLoadError
    return len(prompts)


def _legacy_backup_path() -> Path:
    ts = generate_timestamp()
    return prompt_history_dir() / f"legacy-imported-{ts}.json.bak"


def ensure_migrated() -> None:
    """Migrate the legacy single-file store into shards once, losslessly."""
    history_dir = prompt_history_dir()
    if history_dir.exists() and history_dir.is_dir():
        return

    legacy_file = legacy_prompt_history_file()
    if not legacy_file.exists():
        return

    entries = _load_legacy_prompt_history_for_write()
    buckets: dict[str, list[PromptEntry]] = {}
    for entry in entries:
        buckets.setdefault(shard_key_for_timestamp(entry.last_used), []).append(entry)

    history_dir.mkdir(parents=True, exist_ok=True)
    written_count = 0
    try:
        for key, shard_entries in buckets.items():
            shard_entries.sort(key=_entry_last_used_sort_key, reverse=True)
            if not save_shard(shard_path(key), shard_entries):
                raise PromptHistoryLoadError
            written_count += len(shard_entries)
        if written_count != len(entries):
            raise PromptHistoryLoadError
        raw_count = _raw_prompt_count(legacy_file)
        if written_count != raw_count:
            raise PromptHistoryLoadError
        backup_path = _legacy_backup_path()
        os.replace(legacy_file, backup_path)
    except Exception:
        for path in iter_shard_paths_newest_first():
            try:
                path.unlink()
            except OSError:
                pass
        try:
            history_dir.rmdir()
        except OSError:
            pass
        raise


def ensure_migrated_for_read() -> None:
    """Ensure migration before a read, taking the global lock only if needed."""
    history_dir = prompt_history_dir()
    legacy_file = legacy_prompt_history_file()
    if history_dir.exists() or not legacy_file.exists():
        return
    with locked_prompt_history():
        ensure_migrated()


def add_or_update_prompt(
    text: str,
    *,
    cancelled: bool = False,
    allow_short: bool = False,
    record_segments: bool = True,
) -> None:
    """Add a new prompt or update an existing prompt's last_used timestamp.

    If a prompt with the same text already exists, updates its last_used timestamp.
    Otherwise, adds a new entry.

    Args:
        text: The prompt text to add or update.
        cancelled: If True, mark this prompt as cancelled (unsent). An existing
            non-cancelled prompt will not be downgraded to cancelled.
        allow_short: If True, record the prompt even when it is shorter than
            the normal history threshold. This is used for replayable generated
            fanout invocations such as a bare xprompt swarm trigger.
        record_segments: If True, multi-prompts also record their individual
            long-enough segments. If False, only the exact prompt text passed by
            the caller is written.

    Placeholder tags are recorded before the history threshold is applied, so
    even a sub-five-word prompt contributes its ``<foobar>`` tags to the common
    placeholder store. Cancelled prompts contribute too: the user wrote those
    tags, and recovering one from an abandoned draft is exactly what makes the
    completion menu feel like it remembers. Span extraction covers the whole
    string, so multi-prompt segments need no separate call.
    """
    from sase.history.prompt_placeholders import record_prompt_placeholders

    record_prompt_placeholders(text)

    if not is_recordable_prompt(text, allow_short=allow_short):
        return

    current_timestamp = generate_timestamp()
    mutations = [_PromptMutation(text=text, cancelled=cancelled)]
    if record_segments:
        mutations.extend(_multi_prompt_segment_mutations(text, cancelled=cancelled))

    _apply_prompt_mutations(mutations, current_timestamp)


def record_failed_launch_prompt(text: str, *, project: str | None = None) -> None:
    """Record a submitted prompt whose launch failed before producing agents.

    Failed launch attempts are different from ordinary prompt-bar cancellation:
    the user submitted the prompt, so even short prompts such as ``#gh:foo`` are
    useful history, and an earlier optimistic successful write must be forced
    back to cancelled.

    The submitted prompt is also preserved in the prompt stash (best-effort) so
    a long prompt remains recoverable through ``gp`` / ``gP`` after the prompt
    bar has been unmounted. ``project`` is optional best-effort metadata for the
    restore picker's project chip; it never gates recovery of the prompt text.

    A failed launch still records the prompt's ``<foobar>`` tags in the common
    placeholder store: the user wrote them, so they stay available in the next
    prompt's completion menu even though the launch produced no agents.
    """
    if not text.strip():
        return

    from sase.history.prompt_placeholders import record_prompt_placeholders

    record_prompt_placeholders(text)

    current_timestamp = generate_timestamp()
    mutations = [_PromptMutation(text=text, cancelled=True, force_cancelled=True)]
    mutations.extend(
        _PromptMutation(
            text=mutation.text,
            cancelled=True,
            force_cancelled=True,
        )
        for mutation in _multi_prompt_segment_mutations(text, cancelled=True)
    )

    _apply_prompt_mutations(mutations, current_timestamp)

    from sase.agent.failed_launch_prompt_stash import stash_failed_launch_prompt

    stash_failed_launch_prompt(text, project=project)


def _multi_prompt_segment_mutations(
    text: str,
    *,
    cancelled: bool,
) -> list[_PromptMutation]:
    """Return history mutations for long-enough multi-prompt segments."""
    from sase.agent.multi_prompt import is_multi_prompt, parse_multi_prompt

    if not is_multi_prompt(text):
        return []

    multi = parse_multi_prompt(text)
    mutations = []
    for segment in multi.segments:
        if not is_recordable_prompt(segment):
            continue
        mutations.append(_PromptMutation(text=segment, cancelled=cancelled))
    return mutations


def _multi_prompt_segment_rewrite_pairs(
    old_text: str,
    new_text: str,
) -> list[tuple[str, str]]:
    """Return exact old/new segment pairs for a rewritten multi-prompt."""
    from sase.agent.multi_prompt import is_multi_prompt, parse_multi_prompt

    if not is_multi_prompt(old_text) or not is_multi_prompt(new_text):
        return []

    old_multi = parse_multi_prompt(old_text)
    new_multi = parse_multi_prompt(new_text)
    if len(old_multi.segments) != len(new_multi.segments):
        return []

    return [
        (old_segment, new_segment)
        for old_segment, new_segment in zip(
            old_multi.segments,
            new_multi.segments,
            strict=True,
        )
        if old_segment != new_segment
    ]


def rewrite_prompt_text_exact(old_text: str, new_text: str) -> int:
    """Rewrite prompt-history entries by exact text match.

    The rewrite is intentionally conservative: it replaces only rows whose
    ``text`` exactly matches *old_text*, plus exact multi-prompt segment rows
    derived from old/new segment pairs. Fuzzy matching is never used.

    Returns the number of history rows whose text changed.

    Raises:
        PromptHistoryLoadError: If the current history cannot be safely loaded
            or saved for mutation.
    """
    if old_text == new_text:
        return 0

    replacements: dict[str, str] = {old_text: new_text}
    replacements.update(_multi_prompt_segment_rewrite_pairs(old_text, new_text))

    with locked_prompt_history():
        ensure_migrated()
        entries: list[PromptEntry] = []
        for path in iter_shard_paths_newest_first():
            shard_entries = load_shard_for_write(path)
            shard_entries.sort(key=_entry_last_used_sort_key, reverse=True)
            entries.extend(shard_entries)

        changed = 0
        for entry in entries:
            replacement = replacements.get(entry.text)
            if replacement is None:
                continue
            entry.text = replacement
            changed += 1

        if changed == 0:
            return 0

        entries.sort(key=_entry_last_used_sort_key, reverse=True)
        deduped = _dedup_entries_newest_first(iter(entries))
        if not save_prompt_history(deduped):
            raise PromptHistoryLoadError
        return changed


def _apply_prompt_mutations(
    mutations: list[_PromptMutation],
    current_timestamp: str,
) -> bool:
    """Apply prompt mutations to the current month shard under the writer lock."""
    with locked_prompt_history():
        try:
            ensure_migrated()
            path = shard_path(shard_key_for_timestamp(current_timestamp))
            prompts = load_shard_for_write(path)
        except PromptHistoryLoadError:
            return False

        for mutation in mutations:
            existing = next((p for p in prompts if p.text == mutation.text), None)
            if existing:
                existing.last_used = current_timestamp
                if mutation.force_cancelled:
                    existing.cancelled = True
                elif not mutation.cancelled:
                    # Normal cancellation only upgrades to non-cancelled, never
                    # downgrades an already-successful prompt.
                    existing.cancelled = False
                continue

            prompts.append(
                PromptEntry(
                    text=mutation.text,
                    timestamp=current_timestamp,
                    last_used=current_timestamp,
                    cancelled=mutation.cancelled,
                )
            )

        prompts.sort(key=_entry_last_used_sort_key, reverse=True)
        return save_shard(path, prompts)


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
