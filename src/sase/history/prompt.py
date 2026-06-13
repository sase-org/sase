"""Prompt history storage and retrieval for sase run commands."""

import fcntl
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from sase.core.paths import sase_home
from sase.core.time import generate_timestamp

_PROMPT_HISTORY_FILE: Path | None = None

# Display settings for fzf
_PROMPT_PREVIEW_LENGTH = 60

# Skip prompts shorter than this — bare xprompt triggers like `#gh:sase` are
# single-token and not meaningful to re-run from history.
_MIN_PROMPT_WORDS = 2


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


# Stable content-addressed prompt IDs are derived from exact prompt text so
# selectors never depend on volatile recency indexes. ``ph_`` plus the first
# twelve hex characters of the SHA-256 digest is short enough to type yet wide
# enough to avoid collisions across a realistic prompt history.
_PROMPT_ID_PREFIX = "ph_"
_PROMPT_ID_HASH_LEN = 12

# Largest prompts / chip counts reported by ``compute_prompt_stats`` default
# to compact top-N slices so stats output stays bounded on huge histories.
_STATS_LARGEST_LIMIT = 5
_STATS_CHIPS_LIMIT = 10
_STATS_PREVIEW_CHARS = 60


def _compute_prompt_hash(text: str) -> str:
    """Return the full lowercase SHA-256 hex digest of exact prompt text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_prompt_id(text: str) -> str:
    """Return the stable ``ph_<sha256[:12]>`` content ID for prompt text."""
    return f"{_PROMPT_ID_PREFIX}{_compute_prompt_hash(text)[:_PROMPT_ID_HASH_LEN]}"


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

    def to_entry(self) -> "PromptEntry":
        """Return the underlying :class:`PromptEntry` for this record."""
        return PromptEntry(
            text=self.text,
            timestamp=self.timestamp,
            last_used=self.last_used,
            cancelled=self.cancelled,
            branch_or_workspace=self.branch_or_workspace,
            workspace=self.workspace,
        )


class PromptSelectorError(ValueError):
    """Base class for prompt selector resolution failures."""


class PromptNotFoundError(PromptSelectorError):
    """Raised when a selector matches no prompt-history record."""

    def __init__(self, selector: str) -> None:
        super().__init__(f"No prompt matches selector: {selector!r}")
        self.selector = selector


class PromptAmbiguousError(PromptSelectorError):
    """Raised when a short selector matches more than one record."""

    def __init__(self, selector: str, matches: list[str]) -> None:
        self.selector = selector
        self.matches = matches
        joined = ", ".join(matches)
        super().__init__(
            f"Selector {selector!r} is ambiguous; matches: {joined}."
            " Use a longer selector or sha256:<full_hash>."
        )


def _record_from_entry(entry: PromptEntry) -> PromptHistoryRecord:
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


@dataclass(frozen=True)
class _PromptMutation:
    """A prompt history mutation to apply under the writer lock."""

    text: str
    cancelled: bool
    force_cancelled: bool = False


class _PromptHistoryLoadError(Exception):
    """Raised when prompt history cannot be loaded for a safe mutation."""


def _prompt_history_file() -> Path:
    return _PROMPT_HISTORY_FILE or sase_home() / "prompt_history.json"


def _prompt_entry_from_json(value: object) -> PromptEntry | None:
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


def _load_prompt_history() -> list[PromptEntry]:
    """Load prompt history from disk.

    Returns:
        List of PromptEntry objects, or empty list if file doesn't exist.
    """
    history_file = _prompt_history_file()
    if not history_file.exists():
        return []

    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)

        prompts = data.get("prompts", [])
        return [
            entry
            for entry in (_prompt_entry_from_json(prompt) for prompt in prompts)
            if entry is not None
        ]
    except (AttributeError, OSError, json.JSONDecodeError, KeyError):
        return []


def _load_prompt_history_for_write() -> list[PromptEntry]:
    """Load prompt history for a writer without masking corrupt/partial files."""
    history_file = _prompt_history_file()
    if not history_file.exists():
        return []

    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)

        prompts = data.get("prompts", [])
        return [
            entry
            for entry in (_prompt_entry_from_json(prompt) for prompt in prompts)
            if entry is not None
        ]
    except (AttributeError, OSError, json.JSONDecodeError, KeyError) as exc:
        raise _PromptHistoryLoadError from exc


def _prompt_history_lock_file() -> Path:
    """Return the lock file path for prompt history mutations."""
    history_file = _prompt_history_file()
    return history_file.with_name(f"{history_file.name}.lock")


@contextmanager
def _locked_prompt_history() -> Iterator[None]:
    """Hold an exclusive lock for prompt-history read/modify/write cycles."""
    lock_file = _prompt_history_lock_file()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _save_prompt_history(prompts: list[PromptEntry]) -> bool:
    """Save prompt history to disk.

    Args:
        prompts: List of PromptEntry objects to save.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        history_file = _prompt_history_file()
        history_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "prompts": [
                {
                    "text": p.text,
                    "timestamp": p.timestamp,
                    "last_used": p.last_used,
                    "cancelled": p.cancelled,
                }
                for p in prompts
            ]
        }
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{history_file.name}.",
            suffix=f".{os.getpid()}.tmp",
            dir=history_file.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, history_file)
        except OSError:
            try:
                temp_path.unlink()
            except OSError:
                pass
            return False
        return True
    except OSError:
        return False


def add_or_update_prompt(
    text: str,
    *,
    cancelled: bool = False,
    allow_short: bool = False,
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
            fanout invocations such as a bare multi-agent xprompt trigger.
    """
    if not allow_short and len(text.split()) < _MIN_PROMPT_WORDS:
        return

    current_timestamp = generate_timestamp()
    mutations = [_PromptMutation(text=text, cancelled=cancelled)]
    mutations.extend(_multi_prompt_segment_mutations(text, cancelled=cancelled))

    _apply_prompt_mutations(mutations, current_timestamp)


def record_failed_launch_prompt(text: str) -> None:
    """Record a submitted prompt whose launch failed before producing agents.

    Failed launch attempts are different from ordinary prompt-bar cancellation:
    the user submitted the prompt, so even short prompts such as ``#gh:foo`` are
    useful history, and an earlier optimistic successful write must be forced
    back to cancelled.
    """
    if not text.strip():
        return

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
        if len(segment.split()) < _MIN_PROMPT_WORDS:
            continue
        mutations.append(_PromptMutation(text=segment, cancelled=cancelled))
    return mutations


def _apply_prompt_mutations(
    mutations: list[_PromptMutation],
    current_timestamp: str,
) -> bool:
    """Apply prompt mutations in one locked read/modify/write cycle."""
    with _locked_prompt_history():
        try:
            prompts = _load_prompt_history_for_write()
        except _PromptHistoryLoadError:
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

        return _save_prompt_history(prompts)


def _format_prompt_for_display(entry: PromptEntry) -> str:
    """Format a prompt entry for fzf display.

    Args:
        entry: The prompt entry to format.

    Returns:
        Formatted display string.
    """
    # Format prompt text: replace newlines with spaces, truncate if needed
    preview = entry.text.replace("\n", " ").replace("\r", " ")
    if len(preview) > _PROMPT_PREVIEW_LENGTH:
        preview = preview[:_PROMPT_PREVIEW_LENGTH] + "..."

    return f"{entry.last_used} | {preview}"


# ---------------------------------------------------------------------------
# Read-only catalog API
# ---------------------------------------------------------------------------


def _filter_records(
    records: list[PromptHistoryRecord],
    *,
    include_cancelled: bool,
    cancelled_only: bool,
    query: str | None,
) -> list[PromptHistoryRecord]:
    """Apply launched/all/cancelled and case-insensitive substring filters."""
    if cancelled_only:
        records = [r for r in records if r.cancelled]
    elif not include_cancelled:
        records = [r for r in records if not r.cancelled]

    if query:
        needle = query.lower()
        records = [r for r in records if needle in r.text.lower()]

    return records


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
    records = [_record_from_entry(entry) for entry in _load_prompt_history()]
    records = _filter_records(
        records,
        include_cancelled=include_cancelled,
        cancelled_only=cancelled_only,
        query=query,
    )
    records.sort(key=lambda r: r.last_used, reverse=True)
    if limit is not None and limit >= 0:
        records = records[:limit]
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
        PromptNotFoundError: the selector is empty, non-hex, or matches nothing.
        PromptAmbiguousError: a short prefix matches more than one record.
    """
    if records is None:
        records = [_record_from_entry(entry) for entry in _load_prompt_history()]

    hexprefix = _normalize_selector(selector)
    if hexprefix is None:
        raise PromptNotFoundError(selector)

    matches = [r for r in records if r.text_sha256.startswith(hexprefix)]
    if not matches:
        raise PromptNotFoundError(selector)

    unique_ids = {r.id for r in matches}
    if len(unique_ids) > 1:
        raise PromptAmbiguousError(selector, sorted(unique_ids))
    return matches[0]


@dataclass(frozen=True)
class PromptLargest:
    """A large prompt summarized by ID and size, with a preview only."""

    id: str
    text_chars: int
    preview: str


@dataclass(frozen=True)
class PromptHistoryStats:
    """Aggregate, full-text-free statistics for the prompt-history store."""

    path: str
    exists: bool
    size_bytes: int
    total: int
    launched: int
    cancelled: int
    oldest_last_used: str | None
    newest_last_used: str | None
    length_percentiles: dict[str, int]
    largest: list[PromptLargest]
    top_chips: list[tuple[str, int]]


def _short_preview(text: str, limit: int = _STATS_PREVIEW_CHARS) -> str:
    """Return a single-line, truncated preview of prompt text."""
    collapsed = " ".join(text.split())
    if len(collapsed) > limit:
        return collapsed[: max(limit - 1, 1)] + "…"
    return collapsed


def _percentile(sorted_values: list[int], pct: float) -> int:
    """Return the nearest-rank ``pct`` percentile of pre-sorted values."""
    if not sorted_values:
        return 0
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _prompt_chips(text: str) -> list[str]:
    """Return xprompt/workflow/directive chips parsed from a prompt.

    Parsing is best-effort; any prompt that the metadata layer cannot parse
    contributes no chips rather than failing the whole stats computation.
    """
    try:
        from sase.history.prompt_metadata import summarize_prompt_for_list

        summary = summarize_prompt_for_list(text)
    except Exception:
        return []

    chips: list[str] = []
    if summary.project_prefix:
        chips.append(summary.project_prefix.rstrip(":"))
    chips.extend(summary.xprompts)
    if summary.directive_token:
        chips.extend(summary.directive_token.split())
    return chips


def compute_prompt_stats() -> PromptHistoryStats:
    """Compute read-only aggregate statistics for the prompt-history store.

    Never echoes full prompt text: the only text exposed is a short preview
    for the largest prompts. Tolerates a missing or corrupt store by reporting
    whatever can be read.
    """
    history_file = _prompt_history_file()
    exists = history_file.exists()
    try:
        size_bytes = history_file.stat().st_size if exists else 0
    except OSError:
        size_bytes = 0

    records = [_record_from_entry(entry) for entry in _load_prompt_history()]
    total = len(records)
    cancelled = sum(1 for r in records if r.cancelled)
    launched = total - cancelled

    last_used_values = sorted(r.last_used for r in records)
    oldest = last_used_values[0] if last_used_values else None
    newest = last_used_values[-1] if last_used_values else None

    lengths = sorted(r.text_chars for r in records)
    percentiles = {
        "p50": _percentile(lengths, 50),
        "p90": _percentile(lengths, 90),
        "p99": _percentile(lengths, 99),
        "max": lengths[-1] if lengths else 0,
    }

    largest = [
        PromptLargest(
            id=r.id,
            text_chars=r.text_chars,
            preview=_short_preview(r.text),
        )
        for r in sorted(records, key=lambda r: r.text_chars, reverse=True)[
            :_STATS_LARGEST_LIMIT
        ]
    ]

    chip_counts: dict[str, int] = {}
    for record in records:
        for chip in _prompt_chips(record.text):
            chip_counts[chip] = chip_counts.get(chip, 0) + 1
    top_chips = sorted(chip_counts.items(), key=lambda kv: (-kv[1], kv[0]))[
        :_STATS_CHIPS_LIMIT
    ]

    return PromptHistoryStats(
        path=str(history_file),
        exists=exists,
        size_bytes=size_bytes,
        total=total,
        launched=launched,
        cancelled=cancelled,
        oldest_last_used=oldest,
        newest_last_used=newest,
        length_percentiles=percentiles,
        largest=largest,
        top_chips=top_chips,
    )


# ---------------------------------------------------------------------------
# Maintenance: doctor (read-only), delete, prune (mutations)
# ---------------------------------------------------------------------------

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
    history_file = _prompt_history_file()
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
    oversized: list[PromptLargest]
    short_recovery: list[PromptLargest]
    fzf_available: bool
    clipboard_available: bool


def compute_prompt_doctor() -> PromptHistoryDoctor:
    """Compute a read-only diagnostic report for the prompt-history store.

    Tolerates a missing or corrupt store: a corrupt top-level file reports
    ``parseable=False`` with zero entries rather than raising. The only text
    exposed is a short preview for oversized and recovery-path prompts.
    """
    from sase.core.clipboard import clipboard_available

    history_file = _prompt_history_file()
    exists = history_file.exists()
    try:
        size_bytes = history_file.stat().st_size if exists else 0
    except OSError:
        size_bytes = 0

    parseable, raw_prompts = _load_raw_prompt_entries()
    entries = [
        entry
        for entry in (_prompt_entry_from_json(raw) for raw in raw_prompts)
        if entry is not None
    ]
    invalid_entries = len(raw_prompts) - len(entries)

    records = [_record_from_entry(entry) for entry in entries]
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
        PromptLargest(id=r.id, text_chars=r.text_chars, preview=_short_preview(r.text))
        for r in sorted(records, key=lambda r: r.text_chars, reverse=True)
        if r.text_chars >= _DOCTOR_OVERSIZE_CHARS
    ][:_DOCTOR_LIST_LIMIT]

    short_recovery = [
        PromptLargest(id=r.id, text_chars=r.text_chars, preview=_short_preview(r.text))
        for r in sorted(records, key=lambda r: r.text_chars)
        if len(r.text.split()) < _MIN_PROMPT_WORDS
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


def delete_prompt(selector: str) -> PromptHistoryRecord:
    """Delete the single prompt resolved by *selector* and return its record.

    Runs under the prompt-history writer lock with atomic replace. A corrupt or
    transiently unreadable store aborts with :class:`PromptStoreCorruptError`
    rather than risking an empty rewrite. Selector failures raise the usual
    :class:`PromptSelectorError` subclasses before any write happens, so a bad
    selector never rewrites the store.
    """
    with _locked_prompt_history():
        try:
            entries = _load_prompt_history_for_write()
        except _PromptHistoryLoadError as exc:
            raise PromptStoreCorruptError from exc

        records = [_record_from_entry(entry) for entry in entries]
        record = resolve_prompt_selector(selector, records=records)
        # Content-addressed IDs mean every entry sharing this prompt's text is
        # the same logical prompt; drop them all so duplicates cannot linger.
        remaining = [entry for entry in entries if entry.text != record.text]
        if not _save_prompt_history(remaining):
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
    removed: list[PromptHistoryRecord]
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
    the supplied constraints. ``keep`` is a hard floor — the newest ``keep``
    entries (over the whole store) always survive, so ``before``/``cancelled``
    can only narrow the removal set, never delete a recent prompt. ``before`` is
    a parsed ``YYmmdd_HHMMSS`` cutoff (see :func:`parse_prune_date`).

    Requires at least one predicate. ``dry_run`` computes the plan without
    mutating. A corrupt store aborts with :class:`PromptStoreCorruptError`.
    """
    if keep is None and before is None and not cancelled_only:
        raise ValueError("prune requires at least one of keep, before, cancelled_only")

    with _locked_prompt_history():
        try:
            entries = _load_prompt_history_for_write()
        except _PromptHistoryLoadError as exc:
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

        removed = [_record_from_entry(entries[i]) for i in removable]
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
        if not _save_prompt_history(remaining):
            raise PromptStoreWriteError
        return replace(plan, applied=True)


def get_prompts_for_fzf(
    *, include_cancelled: bool = False
) -> list[tuple[str, PromptEntry]]:
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
        (_format_prompt_for_display(entry), entry)
        for entry in (record.to_entry() for record in records)
    ]
