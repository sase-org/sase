"""Prompt history aggregate statistics."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sase.history import prompt_catalog as catalog
from sase.history import prompt_store as store

# Largest prompts / chip counts reported by ``compute_prompt_stats`` default
# to compact top-N slices so stats output stays bounded on huge histories.
_STATS_LARGEST_LIMIT = 5
_STATS_CHIPS_LIMIT = 10
_STATS_PREVIEW_CHARS = 60


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
    shard_count: int
    total: int
    launched: int
    cancelled: int
    oldest_last_used: str | None
    newest_last_used: str | None
    length_percentiles: dict[str, int]
    largest: list[PromptLargest]
    top_chips: list[tuple[str, int]]


def short_preview(text: str, limit: int = _STATS_PREVIEW_CHARS) -> str:
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
    records = [
        catalog.record_from_entry(entry) for entry in store.load_all_prompt_history()
    ]
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
            preview=short_preview(r.text),
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
        path=str(history_dir),
        exists=exists,
        size_bytes=size_bytes,
        shard_count=len(shard_paths),
        total=total,
        launched=launched,
        cancelled=cancelled,
        oldest_last_used=oldest,
        newest_last_used=newest,
        length_percentiles=percentiles,
        largest=largest,
        top_chips=top_chips,
    )
