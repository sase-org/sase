"""Prompt history diagnostics, delete, and prune operations."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace

from sase.history import prompt_catalog as catalog
from sase.history import prompt_stats as stats
from sase.history import prompt_store as store

# Prompts at or above this size are flagged by ``doctor`` as oversized so a
# huge accidental paste is easy to find and prune. Top-N slices keep doctor
# output bounded and full-text-free on large stores.
_DOCTOR_OVERSIZE_CHARS = 10_000
_DOCTOR_LIST_LIMIT = 5


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


def _load_raw_prompt_entries() -> tuple[bool, list[object]]:
    """Return ``(parseable, raw_prompt_list)`` for read-only diagnostics.

    ``parseable`` is False when the file exists but is not a JSON object with a
    ``prompts`` list. The raw list is returned untouched so ``doctor`` can count
    individually invalid entries without discarding them silently.
    """
    history_file = store.prompt_history_file()
    if not history_file.exists():
        return True, []

    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False, []

    if not isinstance(data, dict):
        return False, []
    prompts = data.get("prompts", [])
    if not isinstance(prompts, list):
        return False, []
    return True, prompts


@dataclass(frozen=True)
class PromptHistoryDoctor:
    """Read-only health report for the prompt-history store (no full text)."""

    path: str
    exists: bool
    size_bytes: int
    parseable: bool
    total: int
    cancelled: int
    invalid_entries: int
    duplicate_ids: list[tuple[str, int]]
    legacy_field_entries: int
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

    history_file = store.prompt_history_file()
    exists = history_file.exists()
    try:
        size_bytes = history_file.stat().st_size if exists else 0
    except OSError:
        size_bytes = 0

    parseable, raw_prompts = _load_raw_prompt_entries()
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
        path=str(history_file),
        exists=exists,
        size_bytes=size_bytes,
        parseable=parseable,
        total=len(records),
        cancelled=cancelled,
        invalid_entries=invalid_entries,
        duplicate_ids=duplicate_ids,
        legacy_field_entries=legacy_field_entries,
        oversized=oversized,
        short_recovery=short_recovery,
        fzf_available=shutil.which("fzf") is not None,
        clipboard_available=clipboard_available(),
    )


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
        # Content-addressed IDs mean every entry sharing this prompt's text is
        # the same logical prompt; drop them all so duplicates cannot linger.
        remaining = [entry for entry in entries if entry.text != record.text]
        if not store.save_prompt_history(remaining):
            raise PromptStoreWriteError
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

    @property
    def kept(self) -> int:
        """Return how many prompts remain after the plan is applied."""
        return self.total - len(self.removed)


def prune_prompts(
    *,
    keep: int | None = None,
    before: str | None = None,
    cancelled_only: bool = False,
    dry_run: bool = False,
) -> PrunePlan:
    """Remove prompts matching every supplied predicate, conservatively.

    Predicates intersect: an entry is removed only when it satisfies *all* of
    the supplied constraints. ``keep`` is a hard floor - the newest ``keep``
    entries (over the whole store) always survive, so ``before``/``cancelled``
    can only narrow the removal set, never delete a recent prompt. ``before`` is
    a parsed ``YYmmdd_HHMMSS`` cutoff (see :func:`parse_prune_date`).

    Requires at least one predicate. ``dry_run`` computes the plan without
    mutating. A corrupt store aborts with :class:`PromptStoreCorruptError`.
    """
    if keep is not None and keep < 0:
        raise ValueError("keep must be greater than or equal to 0")
    if keep is None and before is None and not cancelled_only:
        raise ValueError("prune requires at least one of keep, before, cancelled_only")

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
        for i in candidates:
            if keep is not None and i in newest_indices:
                continue
            if before is not None and not (entries[i].last_used < before):
                continue
            removable.append(i)

        removed = [catalog.record_from_entry(entries[i]) for i in removable]
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
        )

        if dry_run or not removable:
            return plan

        remove_set = set(removable)
        remaining = [e for i, e in enumerate(entries) if i not in remove_set]
        if not store.save_prompt_history(remaining):
            raise PromptStoreWriteError
        return replace(plan, applied=True)
