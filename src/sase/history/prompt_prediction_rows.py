"""History rows and project resolution for next-word prompt prediction.

Builds :class:`PromptPredictionRow` inputs for the frozen
``sase_core_rs.PromptPredictionCorpus`` compiler from the sharded prompt
history, the same way :func:`build_prompt_word_index` reads it
(``shard_limit`` 24, ``prompt_limit`` 20000, dedup newest first). Rows carry
the entry's ``origin`` (so the core can exclude machine-generated prompts),
its ``cancelled`` state, and a canonical project key resolved through
:class:`PromptPredictionProjectResolver`.

The resolver snapshot is built off-thread from
:class:`PromptHistoryProjectCatalog` and resolves per draft with pure
parsers only (VCS workflow tags and ``+project`` tags), so
:meth:`PromptPredictionProjectResolver.resolve` is keystroke-safe: no disk
I/O, no catalog rebuild, no Rust binding.
"""

from __future__ import annotations

import calendar
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sase.core.prompt_prediction_wire import PromptPredictionRow
from sase.history.prompt_store import (
    PromptEntry,
    dedup_prompt_entries_newest_first,
    iter_shard_paths_newest_first,
    load_shard,
)
from sase.history.prompt_word_deletions import (
    PromptWordDeletionsSourceToken,
    prompt_word_deletions_source_token,
)

log = logging.getLogger(__name__)

_SOURCE_TOKEN_SHARD_LIMIT_DEFAULT: Final = 24
_SOURCE_TOKEN_PROMPT_LIMIT_DEFAULT: Final = 20000

#: Staleness token for the prediction row inputs: shard stats plus the
#: history-word deletions token (deletions feed ``excluded_words``).
PromptPredictionSourceToken = tuple[
    tuple[tuple[str, int, int], ...],
    PromptWordDeletionsSourceToken,
]

#: Fallback resolver used before the first catalog snapshot lands.
ResolvePromptProject = Callable[[str], str | None]

_PLUS_TAG_RE: Final = re.compile(
    r"(?<![\w+])\+([A-Za-z](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_])?)"
)


@dataclass(frozen=True, slots=True)
class PromptPredictionProjectResolver:
    """One immutable project-key snapshot for prediction row building.

    ``mapping`` maps every known spelling (project keys, aliases, and
    owner/repo raw refs, all casefolded) to its canonical project key.
    """

    mapping: dict[str, str]

    def resolve(self, text: str) -> str | None:
        """Return the canonical project key for *text*'s draft tag.

        Parses the draft's VCS workflow tag first, then its first
        ``+project`` tag outside launch-inert zones. A tag that resolves
        against the snapshot returns its canonical key; a tag with no
        snapshot hit falls back to its lowercase text. Drafts with no tag
        return ``None`` so the caller can fall back to the prompt bar's
        known project.
        """
        raw_ref = _draft_tag_raw_ref(text)
        if raw_ref is None:
            return None
        return self.mapping.get(raw_ref.casefold(), raw_ref.lower())


def build_prompt_prediction_project_resolver() -> PromptPredictionProjectResolver:
    """Build a resolver snapshot from local project records.

    Never raises: a failed catalog load (disk, provider records) yields an
    empty snapshot whose tags fall back to lowercase text.
    """
    from sase.history.prompt_history_project_filter import (
        PromptHistoryProjectCatalog,
    )

    try:
        catalog = PromptHistoryProjectCatalog.load()
    except Exception:
        log.debug("Prompt prediction project catalog load failed", exc_info=True)
        return PromptPredictionProjectResolver(mapping={})
    mapping: dict[str, str] = {}
    for entry in catalog.entries:
        mapping.setdefault(entry.key.casefold(), entry.key)
        for spelling in (*entry.aliases, *entry.raw_refs):
            if spelling:
                mapping.setdefault(spelling.casefold(), entry.key)
    return PromptPredictionProjectResolver(mapping=mapping)


def build_prompt_prediction_rows(
    *,
    shard_limit: int | None = _SOURCE_TOKEN_SHARD_LIMIT_DEFAULT,
    prompt_limit: int | None = _SOURCE_TOKEN_PROMPT_LIMIT_DEFAULT,
    shard_paths: Iterable[Path] | None = None,
    load_shard_func: Callable[[Path], list[PromptEntry]] = load_shard,
    resolve_project: ResolvePromptProject | None = None,
) -> list[PromptPredictionRow]:
    """Build prediction rows from prompt-history shards, newest first.

    Mirrors :func:`build_prompt_word_index` bounds and dedups exact-text
    duplicates newest first (typed-wins origin merge), so the compiled
    corpus counts each prompt once at its newest epoch.
    """
    entries = _load_history_entries_newest_first(
        shard_paths=shard_paths,
        shard_limit=shard_limit,
        prompt_limit=prompt_limit,
        load_shard_func=load_shard_func,
    )
    deduped = dedup_prompt_entries_newest_first(iter(entries))
    resolve = resolve_project or (lambda _text: None)
    return [
        PromptPredictionRow(
            text=entry.text,
            epoch_seconds=_entry_epoch_seconds(entry),
            project=resolve(entry.text),
            origin=entry.origin,
            cancelled=entry.cancelled,
        )
        for entry in deduped
    ]


def prompt_prediction_source_token(
    *,
    shard_limit: int | None = _SOURCE_TOKEN_SHARD_LIMIT_DEFAULT,
    shard_paths: Iterable[Path] | None = None,
) -> PromptPredictionSourceToken:
    """Return a cheap staleness token for the prediction row inputs."""
    shards: list[tuple[str, int, int]] = []
    paths = (
        tuple(iter_shard_paths_newest_first())
        if shard_paths is None
        else tuple(shard_paths)
    )
    for shard_index, path in enumerate(paths):
        if shard_limit is not None and shard_index >= shard_limit:
            break
        shards.append(_shard_token(path))
    return (tuple(shards), prompt_word_deletions_source_token())


def normalize_session_text(text: str) -> str:
    """Return the membership key used to prune session texts from history."""
    return text.strip().casefold()


def _load_history_entries_newest_first(
    *,
    shard_paths: Iterable[Path] | None,
    shard_limit: int | None,
    prompt_limit: int | None,
    load_shard_func: Callable[[Path], list[PromptEntry]],
) -> list[PromptEntry]:
    paths = (
        tuple(iter_shard_paths_newest_first())
        if shard_paths is None
        else tuple(shard_paths)
    )
    entries: list[PromptEntry] = []
    for shard_index, path in enumerate(paths):
        if shard_limit is not None and shard_index >= shard_limit:
            log.info("Prompt prediction rows stopped after shard_limit=%s", shard_limit)
            break
        if prompt_limit is not None and len(entries) >= prompt_limit:
            log.info(
                "Prompt prediction rows stopped after prompt_limit=%s", prompt_limit
            )
            break
        shard_entries = sorted(
            load_shard_func(path), key=lambda entry: entry.last_used, reverse=True
        )
        for entry in shard_entries:
            if prompt_limit is not None and len(entries) >= prompt_limit:
                break
            entries.append(entry)
    return entries


def _entry_epoch_seconds(entry: PromptEntry) -> int:
    """Return *entry*'s epoch, preferring ``last_used`` over ``timestamp``."""
    return _parse_sase_timestamp_epoch(entry.last_used) or _parse_sase_timestamp_epoch(
        entry.timestamp
    )


def _parse_sase_timestamp_epoch(timestamp: str) -> int:
    """Parse a SASE ``YYMMDD_HHMMSS`` timestamp to epoch seconds (0 on junk)."""
    raw = timestamp.strip()
    if len(raw) != 13 or raw[6] != "_":
        return 0
    try:
        year = _full_year(int(raw[0:2]))
        month = int(raw[2:4])
        day = int(raw[4:6])
        hour = int(raw[7:9])
        minute = int(raw[9:11])
        second = int(raw[11:13])
    except ValueError:
        return 0
    if (
        not 1 <= month <= 12
        or not 1 <= day <= calendar.monthrange(year, month)[1]
        or not 0 <= hour <= 23
        or not 0 <= minute <= 59
        or not 0 <= second <= 59
    ):
        return 0
    try:
        return int(time.mktime((year, month, day, hour, minute, second, -1, -1, -1)))
    except (OverflowError, ValueError):
        return 0


def _full_year(two_digit_year: int) -> int:
    if two_digit_year <= 68:
        return 2000 + two_digit_year
    return 1900 + two_digit_year


def _shard_token(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _draft_tag_raw_ref(text: str) -> str | None:
    """Return the draft's VCS or ``+project`` tag ref, earliest tag wins."""
    vcs_span, vcs_ref = _vcs_tag_ref(text)
    tag_span, tag_name = _plus_tag_candidate(text)
    if vcs_ref is not None and (tag_name is None or vcs_span <= tag_span):
        return vcs_ref
    return tag_name


def _vcs_tag_ref(text: str) -> tuple[int, str | None]:
    """Return the leading VCS tag's ``(offset, ref)`` (``None`` ref if absent)."""
    try:
        from sase.macro._parsing_vcs_tags import (
            extract_project_from_vcs_tag,
            find_vcs_workflow_tag_span,
        )
    except Exception:
        return (0, None)
    try:
        span = find_vcs_workflow_tag_span(text)
    except Exception:
        return (0, None)
    if span is None:
        return (0, None)
    try:
        ref = extract_project_from_vcs_tag(text[span[0] : span[1]])
    except Exception:
        return (span[0], None)
    return (span[0], ref)


def _plus_tag_candidate(text: str) -> tuple[int, str | None]:
    """Return the first ``+project`` tag's ``(offset, name)`` outside inert zones."""
    if "+" not in text:
        return (0, None)
    try:
        from sase.project_tags import is_project_tag_name
        from sase.macro._literal_zones import literal_zone_ranges
    except Exception:
        return (0, None)
    try:
        inert = literal_zone_ranges(text)
    except Exception:
        inert = []
    for match in _PLUS_TAG_RE.finditer(text):
        start, name = match.start(), match.group(1)
        if any(zone_start <= start < zone_end for zone_start, zone_end in inert):
            continue
        try:
            valid = is_project_tag_name(name)
        except Exception:
            valid = False
        if valid:
            return (start, name)
    return (0, None)


__all__ = [
    "PromptPredictionProjectResolver",
    "PromptPredictionSourceToken",
    "ResolvePromptProject",
    "build_prompt_prediction_project_resolver",
    "build_prompt_prediction_rows",
    "normalize_session_text",
    "prompt_prediction_source_token",
]
