"""Read-only prompt history catalog and selector helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from sase.history import prompt_store as store

# Stable content-addressed prompt IDs are derived from exact prompt text so
# selectors never depend on volatile recency indexes. ``ph_`` plus the first
# twelve hex characters of the SHA-256 digest is short enough to type yet wide
# enough to avoid collisions across a realistic prompt history.
_PROMPT_ID_PREFIX = "ph_"
_PROMPT_ID_HASH_LEN = 12


def _compute_prompt_hash(text: str) -> str:
    """Return the full lowercase SHA-256 hex digest of exact prompt text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PromptHistoryRecord:
    """A catalog view of one prompt-history entry with a stable content ID."""

    id: str
    text_sha256: str
    text: str
    timestamp: str
    last_used: str
    cancelled: bool
    branch_or_workspace: str = ""
    workspace: str = ""

    @property
    def text_chars(self) -> int:
        """Return the character length of the exact prompt text."""
        return len(self.text)

    def to_entry(self) -> store.PromptEntry:
        """Return the underlying :class:`PromptEntry` for this record."""
        return store.PromptEntry(
            text=self.text,
            timestamp=self.timestamp,
            last_used=self.last_used,
            cancelled=self.cancelled,
            branch_or_workspace=self.branch_or_workspace,
            workspace=self.workspace,
        )


@dataclass(frozen=True)
class PromptHistoryPageCursor:
    """Cursor for shard-backed prompt-history pagination."""

    shard_index: int = 0
    offset: int = 0
    seen_texts: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PromptHistoryPage:
    """One page of prompt-history records plus a cursor for older records."""

    records: list[PromptHistoryRecord]
    next_cursor: PromptHistoryPageCursor | None
    exhausted: bool


class PromptSelectorError(ValueError):
    """Base class for prompt selector resolution failures."""


class _PromptNotFoundError(PromptSelectorError):
    """Raised when a selector matches no prompt-history record."""

    def __init__(self, selector: str) -> None:
        super().__init__(f"No prompt matches selector: {selector!r}")
        self.selector = selector


class _PromptAmbiguousError(PromptSelectorError):
    """Raised when a short selector matches more than one record."""

    def __init__(self, selector: str, matches: list[str]) -> None:
        self.selector = selector
        self.matches = matches
        joined = ", ".join(matches)
        super().__init__(
            f"Selector {selector!r} is ambiguous; matches: {joined}."
            " Use a longer selector or sha256:<full_hash>."
        )


def record_from_entry(entry: store.PromptEntry) -> PromptHistoryRecord:
    """Build a :class:`PromptHistoryRecord` from a stored entry."""
    digest = _compute_prompt_hash(entry.text)
    return PromptHistoryRecord(
        id=f"{_PROMPT_ID_PREFIX}{digest[:_PROMPT_ID_HASH_LEN]}",
        text_sha256=digest,
        text=entry.text,
        timestamp=entry.timestamp,
        last_used=entry.last_used,
        cancelled=entry.cancelled,
        branch_or_workspace=entry.branch_or_workspace,
        workspace=entry.workspace,
    )


def _filter_records(
    records: Iterable[PromptHistoryRecord],
    *,
    include_cancelled: bool,
    cancelled_only: bool,
    query: str | None,
) -> list[PromptHistoryRecord]:
    """Apply launched/all/cancelled and case-insensitive substring filters."""
    records = list(records)
    if cancelled_only:
        records = [r for r in records if r.cancelled]
    elif not include_cancelled:
        records = [r for r in records if not r.cancelled]

    if query:
        needle = query.lower()
        records = [r for r in records if needle in r.text.lower()]

    return records


def _record_matches_filters(
    record: PromptHistoryRecord,
    *,
    include_cancelled: bool,
    cancelled_only: bool,
    query: str | None,
) -> bool:
    if cancelled_only:
        if not record.cancelled:
            return False
    elif not include_cancelled and record.cancelled:
        return False

    if query and query.lower() not in record.text.lower():
        return False
    return True


def _load_page_from_shards(
    *,
    page_size: int,
    cursor: PromptHistoryPageCursor | None,
    include_cancelled: bool,
    cancelled_only: bool,
    query: str | None,
) -> PromptHistoryPage:
    if page_size <= 0:
        start = cursor or PromptHistoryPageCursor()
        return PromptHistoryPage(records=[], next_cursor=start, exhausted=False)

    try:
        store.ensure_migrated_for_read()
    except store.PromptHistoryLoadError:
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    shard_paths = list(store.iter_shard_paths_newest_first())
    if not shard_paths:
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    current = cursor or PromptHistoryPageCursor()
    shard_index = current.shard_index
    offset = current.offset
    seen = set(current.seen_texts)
    records: list[PromptHistoryRecord] = []

    while shard_index < len(shard_paths):
        entries = store.load_shard(shard_paths[shard_index])
        entries.sort(key=lambda entry: entry.last_used, reverse=True)
        if offset >= len(entries):
            shard_index += 1
            offset = 0
            continue

        while offset < len(entries):
            entry = entries[offset]
            offset += 1
            if entry.text in seen:
                continue
            seen.add(entry.text)

            record = record_from_entry(entry)
            if not _record_matches_filters(
                record,
                include_cancelled=include_cancelled,
                cancelled_only=cancelled_only,
                query=query,
            ):
                continue
            records.append(record)
            if len(records) >= page_size:
                next_cursor = PromptHistoryPageCursor(
                    shard_index=shard_index,
                    offset=offset,
                    seen_texts=frozenset(seen),
                )
                return PromptHistoryPage(
                    records=records,
                    next_cursor=next_cursor,
                    exhausted=False,
                )

        shard_index += 1
        offset = 0

    return PromptHistoryPage(records=records, next_cursor=None, exhausted=True)


def load_prompt_record_page(
    *,
    page_size: int = 250,
    cursor: PromptHistoryPageCursor | None = None,
    include_cancelled: bool = False,
    cancelled_only: bool = False,
    query: str | None = None,
) -> PromptHistoryPage:
    """Load one deduped recency page from prompt-history shards."""
    return _load_page_from_shards(
        page_size=page_size,
        cursor=cursor,
        include_cancelled=include_cancelled,
        cancelled_only=cancelled_only,
        query=query,
    )


def list_prompt_records(
    *,
    include_cancelled: bool = False,
    cancelled_only: bool = False,
    query: str | None = None,
    limit: int | None = None,
) -> list[PromptHistoryRecord]:
    """Return recency-ordered prompt-history records.

    Records are sorted by ``last_used`` descending. ``cancelled_only`` (the
    ``--cancelled`` view) takes precedence over ``include_cancelled`` (the
    ``--all`` view); the default excludes cancelled prompts. ``query`` is a
    case-insensitive substring filter over exact prompt text. ``limit`` is
    applied after sorting; ``None`` returns every matching record.
    """
    if limit is not None and limit >= 0:
        records: list[PromptHistoryRecord] = []
        cursor: PromptHistoryPageCursor | None = None
        exhausted = False
        while len(records) < limit and not exhausted:
            page = load_prompt_record_page(
                page_size=limit - len(records),
                cursor=cursor,
                include_cancelled=include_cancelled,
                cancelled_only=cancelled_only,
                query=query,
            )
            records.extend(page.records)
            cursor = page.next_cursor
            exhausted = page.exhausted or cursor is None
        return records

    records = [record_from_entry(entry) for entry in store.load_all_prompt_history()]
    records = _filter_records(
        records,
        include_cancelled=include_cancelled,
        cancelled_only=cancelled_only,
        query=query,
    )
    records.sort(key=lambda r: r.last_used, reverse=True)
    return records


def _normalize_selector(selector: str) -> str | None:
    """Return the lowercase hex prefix a selector resolves to, or ``None``.

    Accepts ``ph_<prefix>``, a bare hash prefix as printed by ``list``, or
    ``sha256:<hash>``. Returns ``None`` for empty or non-hex selectors.
    """
    sel = selector.strip()
    if sel.startswith("sha256:"):
        hexprefix = sel[len("sha256:") :].strip().lower()
    elif sel.startswith(_PROMPT_ID_PREFIX):
        hexprefix = sel[len(_PROMPT_ID_PREFIX) :].strip().lower()
    else:
        hexprefix = sel.lower()

    if not hexprefix or any(c not in "0123456789abcdef" for c in hexprefix):
        return None
    return hexprefix


def resolve_prompt_selector(
    selector: str,
    *,
    records: list[PromptHistoryRecord] | None = None,
) -> PromptHistoryRecord:
    """Resolve a selector to a single record, with collision diagnostics.

    Args:
        selector: ``ph_<prefix>``, a bare hash prefix, or ``sha256:<hash>``.
        records: Optional pre-loaded records (e.g. a filtered subset). When
            omitted, the full history is loaded.

    Raises:
        PromptSelectorError: the selector is empty, non-hex, matches nothing, or
            (as a short prefix) matches more than one record.
    """
    if records is None:
        records = [
            record_from_entry(entry) for entry in store.load_all_prompt_history()
        ]

    hexprefix = _normalize_selector(selector)
    if hexprefix is None:
        raise _PromptNotFoundError(selector)

    matches = [r for r in records if r.text_sha256.startswith(hexprefix)]
    if not matches:
        raise _PromptNotFoundError(selector)

    unique_ids = {r.id for r in matches}
    if len(unique_ids) > 1:
        raise _PromptAmbiguousError(selector, sorted(unique_ids))
    return matches[0]


def get_prompts_for_fzf(
    *, include_cancelled: bool = False
) -> list[tuple[str, store.PromptEntry]]:
    """Get prompts formatted for fzf display.

    Prompts are sorted by ``last_used`` descending. This is a thin
    compatibility wrapper over :func:`list_prompt_records` for callers that
    still consume the legacy ``(display_string, PromptEntry)`` shape.

    Args:
        include_cancelled: If True, include cancelled prompts in results.

    Returns:
        List of (display_string, PromptEntry) tuples sorted for fzf display.
    """
    records = list_prompt_records(include_cancelled=include_cancelled)
    return [
        (store.format_prompt_for_display(entry), entry)
        for entry in (record.to_entry() for record in records)
    ]
