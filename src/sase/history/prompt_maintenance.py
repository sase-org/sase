"""Prompt history diagnostics, delete, and prune operations."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from sase.core.prompt_origin import prompt_looks_generated
from sase.core.time import generate_timestamp
from sase.history import prompt_catalog as catalog
from sase.history import prompt_stats as stats
from sase.history import prompt_store as store

# Prompts at or above this size are flagged by ``doctor`` as oversized so a
# huge accidental paste is easy to find and prune. Top-N slices keep doctor
# output bounded and full-text-free on large stores.
_DOCTOR_OVERSIZE_CHARS = 10_000
_DOCTOR_LIST_LIMIT = 5

# Preview samples per prune tier (explicit generated vs. legacy heuristic)
# shown by ``sase prompt prune --dry-run``. Samples are truncated previews,
# never full prompt text.
_PRUNE_SAMPLE_LIMIT = 3


class PromptStoreCorruptError(Exception):
    """Raised when a mutation aborts because the store is unreadable.

    Write commands must never overwrite a corrupt or transiently unreadable
    store with a fresh (possibly empty) file, so they surface this instead.
    """

    def __init__(self) -> None:
        super().__init__(
            "prompt history is unreadable; refusing to rewrite a corrupt store"
        )


class PromptStoreWriteError(Exception):
    """Raised when a mutation cannot be persisted to disk."""

    def __init__(self) -> None:
        super().__init__("failed to write prompt history")


class PromptDateError(ValueError):
    """Raised when a prune date cannot be parsed unambiguously."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(
            f"Could not parse date {value!r}. Use YYYY-MM-DD (e.g. 2026-01-01),"
            " YYmmdd (e.g. 260101), or YYmmdd_HHMMSS (e.g. 260101_143000)."
        )


def parse_prune_date(value: str) -> str:
    """Parse a prune cutoff into a comparable ``YYmmdd_HHMMSS`` timestamp.

    Accepts ``YYYY-MM-DD``, ``YYmmdd``, and SASE ``YYmmdd_HHMMSS`` timestamps.
    Date-only inputs anchor at midnight (``_000000``) so ``--before`` removes
    entries recorded strictly before the start of that day. Ambiguous or
    invalid inputs raise :class:`PromptDateError` with concrete examples.
    """
    from datetime import datetime

    raw = value.strip()
    try:
        if "-" in raw:
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%y%m%d_000000")
        if "_" in raw:
            return datetime.strptime(raw, "%y%m%d_%H%M%S").strftime("%y%m%d_%H%M%S")
        if len(raw) == 6 and raw.isdigit():
            return datetime.strptime(raw, "%y%m%d").strftime("%y%m%d_000000")
    except ValueError:
        pass
    raise PromptDateError(value)


def _load_raw_prompt_entries_from_path(path: Path) -> tuple[bool, list[object]]:
    if not path.exists():
        return True, []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False, []

    if not isinstance(data, dict):
        return False, []
    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        return False, []
    return True, prompts


def _load_raw_prompt_entries() -> tuple[bool, list[object]]:
    """Return ``(parseable, raw_prompt_list)`` for read-only diagnostics.

    ``parseable`` is False when any store file is not a JSON object with a
    ``prompts`` list. The raw list is returned untouched so ``doctor`` can count
    individually invalid entries without discarding them silently.
    """
    try:
        store.ensure_migrated_for_read()
    except store.PromptHistoryLoadError:
        return _load_raw_prompt_entries_from_path(store.legacy_prompt_history_file())

    shard_paths = list(store.iter_shard_paths_newest_first())
    if not shard_paths:
        return True, []

    parseable = True
    raw_prompts: list[object] = []
    for path in shard_paths:
        shard_parseable, shard_prompts = _load_raw_prompt_entries_from_path(path)
        parseable = parseable and shard_parseable
        raw_prompts.extend(shard_prompts)
    return parseable, raw_prompts


@dataclass(frozen=True)
class PromptHistoryDoctor:
    """Read-only health report for the prompt-history store (no full text)."""

    path: str
    exists: bool
    size_bytes: int
    shard_count: int
    parseable: bool
    total: int
    cancelled: int
    invalid_entries: int
    duplicate_ids: list[tuple[str, int]]
    legacy_field_entries: int
    typed_origin_count: int
    generated_origin_count: int
    missing_origin_count: int
    legacy_heuristic_count: int
    oversized: list[stats.PromptLargest]
    short_recovery: list[stats.PromptLargest]
    fzf_available: bool
    clipboard_available: bool


def compute_prompt_doctor() -> PromptHistoryDoctor:
    """Compute a read-only diagnostic report for the prompt-history store.

    Tolerates a missing or corrupt store: a corrupt top-level file reports
    ``parseable=False`` with zero entries rather than raising. The only text
    exposed is a short preview for oversized and recovery-path prompts.
    """
    from sase.core.clipboard import clipboard_available

    parseable, raw_prompts = _load_raw_prompt_entries()
    history_dir = store.prompt_history_dir()
    legacy_file = store.legacy_prompt_history_file()
    shard_paths = list(store.iter_shard_paths_newest_first())
    exists = history_dir.exists() or legacy_file.exists()
    size_bytes = 0
    for path in shard_paths or ([legacy_file] if legacy_file.exists() else []):
        try:
            size_bytes += path.stat().st_size
        except OSError:
            pass
    entries = [
        entry
        for entry in (store.prompt_entry_from_json(raw) for raw in raw_prompts)
        if entry is not None
    ]
    invalid_entries = len(raw_prompts) - len(entries)

    records = [catalog.record_from_entry(entry) for entry in entries]
    cancelled = sum(1 for r in records if r.cancelled)

    id_counts: dict[str, int] = {}
    for record in records:
        id_counts[record.id] = id_counts.get(record.id, 0) + 1
    duplicate_ids = sorted(
        ((pid, count) for pid, count in id_counts.items() if count > 1),
        key=lambda kv: (-kv[1], kv[0]),
    )

    legacy_field_entries = sum(
        1 for entry in entries if entry.workspace or entry.branch_or_workspace
    )

    typed_origin_count = sum(1 for entry in entries if entry.origin == "typed")
    generated_origin_count = sum(1 for entry in entries if entry.origin == "generated")
    missing_origin_texts = [entry.text for entry in entries if entry.origin is None]
    legacy_heuristic_count = sum(
        1 for text in missing_origin_texts if prompt_looks_generated(text)
    )

    oversized = [
        stats.PromptLargest(
            id=r.id,
            text_chars=r.text_chars,
            preview=stats.short_preview(r.text),
        )
        for r in sorted(records, key=lambda r: r.text_chars, reverse=True)
        if r.text_chars >= _DOCTOR_OVERSIZE_CHARS
    ][:_DOCTOR_LIST_LIMIT]

    short_recovery = [
        stats.PromptLargest(
            id=r.id,
            text_chars=r.text_chars,
            preview=stats.short_preview(r.text),
        )
        for r in sorted(records, key=lambda r: r.text_chars)
        if len(r.text.split()) < store._MIN_PROMPT_WORDS
    ][:_DOCTOR_LIST_LIMIT]

    return PromptHistoryDoctor(
        path=str(history_dir),
        exists=exists,
        size_bytes=size_bytes,
        shard_count=len(shard_paths),
        parseable=parseable,
        total=len(records),
        cancelled=cancelled,
        invalid_entries=invalid_entries,
        duplicate_ids=duplicate_ids,
        legacy_field_entries=legacy_field_entries,
        typed_origin_count=typed_origin_count,
        generated_origin_count=generated_origin_count,
        missing_origin_count=len(missing_origin_texts),
        legacy_heuristic_count=legacy_heuristic_count,
        oversized=oversized,
        short_recovery=short_recovery,
        fzf_available=shutil.which("fzf") is not None,
        clipboard_available=clipboard_available(),
    )


def _save_or_remove_shard(path: Path, entries: list[store.PromptEntry]) -> bool:
    if entries:
        entries.sort(key=lambda entry: entry.last_used, reverse=True)
        return store.save_shard(path, entries)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def _remove_prompt_texts_from_shards(texts: set[str]) -> None:
    if not texts:
        return
    for path in list(store.iter_shard_paths_newest_first()):
        entries = store.load_shard_for_write(path)
        remaining = [entry for entry in entries if entry.text not in texts]
        if len(remaining) == len(entries):
            continue
        if not _save_or_remove_shard(path, remaining):
            raise PromptStoreWriteError


def delete_prompt(selector: str) -> catalog.PromptHistoryRecord:
    """Delete the single prompt resolved by *selector* and return its record.

    Runs under the prompt-history writer lock with atomic replace. A corrupt or
    transiently unreadable store aborts with :class:`PromptStoreCorruptError`
    rather than risking an empty rewrite. Selector failures raise the usual
    :class:`PromptSelectorError` subclasses before any write happens, so a bad
    selector never rewrites the store.
    """
    with store.locked_prompt_history():
        try:
            entries = store.load_prompt_history_for_write()
        except store.PromptHistoryLoadError as exc:
            raise PromptStoreCorruptError from exc

        records = [catalog.record_from_entry(entry) for entry in entries]
        record = catalog.resolve_prompt_selector(selector, records=records)
        try:
            _remove_prompt_texts_from_shards({record.text})
        except store.PromptHistoryLoadError as exc:
            raise PromptStoreCorruptError from exc
        return record


@dataclass(frozen=True)
class PrunePlan:
    """A computed prune plan: what would be (or was) removed, and the funnel.

    The per-predicate counts (``beyond_keep_count``, ``older_than_count``)
    describe how many eligible entries each supplied predicate matches on its
    own, so callers can explain exactly why the removed total is what it is.
    """

    total: int
    removed: list[catalog.PromptHistoryRecord]
    candidate_count: int
    keep: int | None
    before: str | None
    cancelled_only: bool
    beyond_keep_count: int
    older_than_count: int
    applied: bool
    generated_only: bool = False
    include_legacy: bool = False
    explicit_generated_count: int = 0
    legacy_heuristic_count: int = 0
    explicit_samples: tuple[str, ...] = ()
    legacy_samples: tuple[str, ...] = ()
    backup_paths: tuple[str, ...] = ()

    @property
    def kept(self) -> int:
        """Return how many prompts remain after the plan is applied."""
        return self.total - len(self.removed)


def _classify_prune_origin_tier(
    entry: store.PromptEntry, *, include_legacy: bool
) -> str | None:
    """Return the prune tier for *entry*: ``"explicit"``, ``"legacy"``, or None.

    ``"explicit"`` rows carry a merged ``generated`` origin, where the merge
    already let a typed copy anywhere in the store win. ``"legacy"`` rows
    carry no origin and match the generated-text heuristic. Anything else is
    not origin-selected.
    """
    if entry.origin == "generated":
        return "explicit"
    if include_legacy and entry.origin is None and prompt_looks_generated(entry.text):
        return "legacy"
    return None


def _backup_prune_shards() -> tuple[str, ...]:
    """Copy every shard file to a timestamped ``.json.bak`` backup.

    Backup names end in ``.bak`` so they never match the ``*.json`` shard
    glob. A same-second repeat gets a numeric suffix instead of overwriting
    the earlier backup. Failures raise :class:`PromptStoreWriteError`
    before any row is removed.
    """
    history_dir = store.prompt_history_dir()
    timestamp = generate_timestamp()
    backups: list[str] = []
    for path in sorted(store.iter_shard_paths_newest_first()):
        stem = path.stem
        backup = history_dir / f"prune-{timestamp}-{stem}.json.bak"
        counter = 1
        while backup.exists():
            counter += 1
            backup = history_dir / f"prune-{timestamp}-{stem}-{counter}.json.bak"
        try:
            shutil.copy2(path, backup)
        except OSError as exc:
            raise PromptStoreWriteError from exc
        backups.append(str(backup))
    return tuple(backups)


def prune_prompts(
    *,
    keep: int | None = None,
    before: str | None = None,
    cancelled_only: bool = False,
    generated_only: bool = False,
    include_legacy: bool = False,
    dry_run: bool = False,
) -> PrunePlan:
    """Remove prompts matching every supplied predicate, conservatively.

    Predicates intersect: an entry is removed only when it satisfies *all* of
    the supplied constraints. ``keep`` is a hard floor - the newest ``keep``
    entries (over the whole store) always survive, so ``before``/``cancelled``
    can only narrow the removal set, never delete a recent prompt. ``before`` is
    a parsed ``YYmmdd_HHMMSS`` cutoff (see :func:`parse_prune_date`).
    ``generated_only`` selects rows whose merged origin is ``generated`` (a
    typed copy anywhere protects every duplicate, since removal works by
    exact text); ``include_legacy`` additionally selects origin-less rows
    the generated-text heuristic flags, and requires ``generated_only``.

    Requires at least one predicate. ``dry_run`` computes the plan without
    mutating. Every apply first writes a timestamped backup of the shard
    files. A corrupt store aborts with :class:`PromptStoreCorruptError`.
    """
    if keep is not None and keep < 0:
        raise ValueError("keep must be greater than or equal to 0")
    if include_legacy and not generated_only:
        raise ValueError("prune --legacy requires --generated")
    if keep is None and before is None and not cancelled_only and not generated_only:
        raise ValueError(
            "prune requires at least one of keep, before, cancelled_only, generated"
        )

    with store.locked_prompt_history():
        try:
            entries = store.load_prompt_history_for_write()
        except store.PromptHistoryLoadError as exc:
            raise PromptStoreCorruptError from exc

        total = len(entries)

        # Newest-N survivors are computed over ALL entries so ``--keep`` stays a
        # hard floor that the other predicates can only narrow.
        newest_indices: set[int] = set()
        if keep is not None:
            by_recency = sorted(
                range(total), key=lambda i: entries[i].last_used, reverse=True
            )
            newest_indices = set(by_recency[: max(keep, 0)])

        candidates = [
            i for i in range(total) if not cancelled_only or entries[i].cancelled
        ]
        beyond_keep_count = (
            sum(1 for i in candidates if i not in newest_indices)
            if keep is not None
            else 0
        )
        older_than_count = (
            sum(1 for i in candidates if entries[i].last_used < before)
            if before is not None
            else 0
        )

        removable: list[int] = []
        removable_tiers: list[str] = []
        for i in candidates:
            if keep is not None and i in newest_indices:
                continue
            if before is not None and not (entries[i].last_used < before):
                continue
            if generated_only:
                tier = _classify_prune_origin_tier(
                    entries[i], include_legacy=include_legacy
                )
                if tier is None:
                    continue
                removable_tiers.append(tier)
            removable.append(i)

        removed = [catalog.record_from_entry(entries[i]) for i in removable]
        tiers = (
            list(zip(removable, removable_tiers, strict=True)) if generated_only else []
        )
        explicit_samples = tuple(
            stats.short_preview(entries[i].text)
            for i, tier in tiers
            if tier == "explicit"
        )[:_PRUNE_SAMPLE_LIMIT]
        legacy_samples = tuple(
            stats.short_preview(entries[i].text)
            for i, tier in tiers
            if tier == "legacy"
        )[:_PRUNE_SAMPLE_LIMIT]
        plan = PrunePlan(
            total=total,
            removed=removed,
            candidate_count=len(candidates),
            keep=keep,
            before=before,
            cancelled_only=cancelled_only,
            beyond_keep_count=beyond_keep_count,
            older_than_count=older_than_count,
            applied=False,
            generated_only=generated_only,
            include_legacy=include_legacy,
            explicit_generated_count=sum(
                1 for tier in removable_tiers if tier == "explicit"
            ),
            legacy_heuristic_count=sum(
                1 for tier in removable_tiers if tier == "legacy"
            ),
            explicit_samples=explicit_samples,
            legacy_samples=legacy_samples,
        )

        if dry_run or not removable:
            return plan

        backup_paths = _backup_prune_shards()
        remove_texts = {entries[i].text for i in removable}
        try:
            _remove_prompt_texts_from_shards(remove_texts)
        except store.PromptHistoryLoadError as exc:
            raise PromptStoreCorruptError from exc
        return replace(plan, applied=True, backup_paths=backup_paths)
