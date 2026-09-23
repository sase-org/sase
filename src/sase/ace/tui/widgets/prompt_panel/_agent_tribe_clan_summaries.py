"""Clan-summary digests for tribe CLAN SUMMARIES sections.

Worker-side, pure presentation logic over the ``clan_summary`` strings that
already sit on clan-container unit roots: every digest is computed off the
Textual event loop and cached by raw-text hash, so the renderer only appends
precomputed strings and replays precomputed style spans.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import blake2b
from typing import TYPE_CHECKING

from rich.style import Style

from ...models._agent_clan_sections import first_meaningful_line
from ._agent_clan_summary_text import clan_summary_markup_text

if TYPE_CHECKING:
    from ...models._agent_clan_sections import ClanAgentIdentity
    from ._agent_tribe_aggregation import TribeUnitSource

type ClanSummaryLineSpan = tuple[str | Style, int, int]

_HEADLINE_MAX_CHARS = 120
_DIGEST_CACHE_MAX_ENTRIES = 256
_HEADING_MARKER_RE = re.compile(r"#{1,6}\s+")
_FIELD_LINE_RE = re.compile(r"^(\s*)([A-Za-z][A-Za-z ]{0,23}):\s+(\S.*)$")
_LABEL_ONLY_RE = re.compile(r"[A-Z][A-Z ]{0,31}")


@dataclass(frozen=True, slots=True)
class _ClanSummaryDigest:
    """Content-only digest of one raw clan summary; cached by raw-text hash."""

    key: str  # 12-hex blake2b of f"{clan}\0{raw}"
    kicker: str  # banner kind, for example "EPIC"; "" when absent
    headline: str  # uniform index text, <=120 chars
    lines: tuple[str, ...]  # plain body lines (banner line removed)
    line_spans: tuple[tuple[ClanSummaryLineSpan, ...], ...]  # spans per body line
    lede_start: int  # body-line index where the lede begins
    lede_count: int  # number of body lines in the lede


@dataclass(frozen=True, slots=True)
class TribeClanSummaryEntry:
    """One clan unit's summary digest plus its roster attribution."""

    unit_identity: ClanAgentIdentity
    unit_label: str
    entry_key: str  # 12-hex blake2b of f"{clan}\0{generation or ''}"
    digest: _ClanSummaryDigest


@dataclass(frozen=True, slots=True)
class TribeClanSummariesSnapshot:
    """Renderer-facing clan summary entries for one tribe panel."""

    entries: tuple[TribeClanSummaryEntry, ...]
    signature: tuple[tuple[ClanAgentIdentity, int, int], ...]


_EMPTY_TRIBE_CLAN_SUMMARIES_SNAPSHOT = TribeClanSummariesSnapshot(
    entries=(),
    signature=(),
)

_digest_cache: OrderedDict[tuple[str, str], _ClanSummaryDigest] = OrderedDict()
_digest_cache_lock = threading.Lock()


def empty_tribe_clan_summaries_snapshot() -> TribeClanSummariesSnapshot:
    """Return the shared empty clan-summaries snapshot."""
    return _EMPTY_TRIBE_CLAN_SUMMARIES_SNAPSHOT


def clan_summaries_signature_for_sources(
    sources: Sequence[TribeUnitSource],
) -> tuple[tuple[ClanAgentIdentity, int, int], ...]:
    """Return the freshness signature for clan-summary sources.

    One ``(unit_identity, len(raw), hash(raw))`` tuple per clan-container
    source with a non-blank summary. ``hash`` of a string is computed once
    per string object, so re-selection costs bounded work per summary.
    """
    signature: list[tuple[ClanAgentIdentity, int, int]] = []
    for source in sources:
        if not source.root.is_clan_container:
            continue
        raw = source.root.clan_summary or ""
        if not raw.strip():
            continue
        signature.append((source.unit_identity, len(raw), hash(raw)))
    return tuple(signature)


def build_tribe_clan_summaries(
    sources: Sequence[TribeUnitSource],
) -> TribeClanSummariesSnapshot:
    """Digest every clan-container summary in roster order.

    Clans without a summary are skipped. One bad summary never fails the
    worker: digesting falls back to plain text for that entry.
    """
    entries: list[TribeClanSummaryEntry] = []
    for source in sources:
        root = source.root
        if not root.is_clan_container:
            continue
        raw = root.clan_summary or ""
        if not raw.strip():
            continue
        clan = root.agent_clan or source.unit_label
        digest = _digest_for_summary(raw, clan)
        entry_key = blake2b(
            f"{clan}\0{root.agent_clan_generation or ''}".encode(
                "utf-8", errors="replace"
            ),
            digest_size=6,
        ).hexdigest()
        entries.append(
            TribeClanSummaryEntry(
                unit_identity=source.unit_identity,
                unit_label=source.unit_label,
                entry_key=entry_key,
                digest=digest,
            )
        )
    return TribeClanSummariesSnapshot(
        entries=tuple(entries),
        signature=clan_summaries_signature_for_sources(sources),
    )


def _digest_for_summary(raw: str, clan: str) -> _ClanSummaryDigest:
    """Return the cached digest for one raw clan summary."""
    cache_key = (
        blake2b(raw.encode("utf-8", errors="replace"), digest_size=16).hexdigest(),
        clan,
    )
    with _digest_cache_lock:
        cached = _digest_cache.get(cache_key)
        if cached is not None:
            _digest_cache.move_to_end(cache_key)
            return cached
    try:
        digest = _build_digest(raw, clan)
    except Exception:
        digest = _fallback_digest(raw, clan)
    with _digest_cache_lock:
        _digest_cache[cache_key] = digest
        _digest_cache.move_to_end(cache_key)
        while len(_digest_cache) > _DIGEST_CACHE_MAX_ENTRIES:
            _digest_cache.popitem(last=False)
    return digest


def _split_body_lines(raw: str) -> tuple[list[str], list[list[ClanSummaryLineSpan]]]:
    """Parse *raw* with clan styling and return plain lines plus per-line spans."""
    parsed = clan_summary_markup_text(raw)
    parsed.rstrip()
    lines: list[str] = []
    spans: list[list[ClanSummaryLineSpan]] = []
    for part in parsed.split("\n", allow_blank=True):
        lines.append(part.plain)
        spans.append([(span.style, span.start, span.end) for span in part.spans])
    return lines, spans


def _build_digest(raw: str, clan: str) -> _ClanSummaryDigest:
    """Digest one raw clan summary into kicker, headline, lede, and body."""
    plain_lines, span_lines = _split_body_lines(raw)
    key = blake2b(
        f"{clan}\0{raw}".encode("utf-8", errors="replace"),
        digest_size=6,
    ).hexdigest()

    index = 0
    while index < len(plain_lines) and not plain_lines[index].strip():
        index += 1
    kicker = ""
    if index < len(plain_lines) and _is_banner_line(plain_lines[index]):
        kicker = _banner_kicker(plain_lines[index], clan)
        index += 1
    while index < len(plain_lines) and not plain_lines[index].strip():
        index += 1
    body_lines = plain_lines[index:]
    body_spans = span_lines[index:]

    headline, truncated, block_start, block_end, label_kicker = _headline_block(
        body_lines, kicker_text=kicker
    )
    if label_kicker is not None:
        kicker = label_kicker
    if not headline:
        headline = kicker
        kicker = ""
    if not headline:
        headline = first_meaningful_line("\n".join(body_lines))
    if truncated:
        # The lede replays the truncated headline block, still capped at 4 lines.
        lede_start, lede_count = _next_lede(body_lines[:block_end], block_start)
    else:
        lede_start, lede_count = _next_lede(body_lines, block_end)
    return _ClanSummaryDigest(
        key=key,
        kicker=kicker,
        headline=headline,
        lines=tuple(body_lines),
        line_spans=tuple(tuple(line) for line in body_spans),
        lede_start=lede_start,
        lede_count=lede_count,
    )


def _fallback_digest(raw: str, clan: str) -> _ClanSummaryDigest:
    """Return a plain digest so one malformed summary never fails the worker."""
    try:
        key = blake2b(
            f"{clan}\0{raw}".encode("utf-8", errors="replace"),
            digest_size=6,
        ).hexdigest()
    except Exception:
        key = "fallback"
    stripped = raw.rstrip()
    lines = stripped.split("\n") if stripped else []
    non_blank = [index for index, line in enumerate(lines) if line.strip()]
    lede = non_blank[:4]
    if lede:
        lede_start, lede_count = lede[0], lede[-1] - lede[0] + 1
    else:
        lede_start, lede_count = 0, 0
    return _ClanSummaryDigest(
        key=key,
        kicker="",
        headline=first_meaningful_line(raw),
        lines=tuple(lines),
        line_spans=tuple(() for _ in lines),
        lede_start=lede_start,
        lede_count=lede_count,
    )


def _is_banner_line(line: str) -> bool:
    """Report whether a first non-blank summary line is a banner line."""
    stripped = line.strip()
    if not stripped:
        return False
    if not stripped[0].isalnum():
        return True
    return (
        not any(char.islower() for char in stripped)
        and len(stripped) <= 60
        and ": " not in stripped
    )


def _banner_kicker(banner: str, clan: str) -> str:
    """Return the banner kind with glyphs and a trailing clan token removed."""
    kicker = re.sub(r"^[^A-Za-z0-9]+", "", banner.strip())
    tokens = kicker.split()
    if tokens and _is_clan_token(tokens[-1], clan):
        tokens.pop()
    return " ".join(" ".join(tokens).split())


def _is_clan_token(token: str, clan: str) -> bool:
    """Report whether *token* names *clan*, plainly or owner-qualified."""
    if not clan or not token:
        return False
    if token == clan:
        return True
    return token.split("/")[-1] == clan


def _is_label_only_line(line: str) -> bool:
    """Report whether *line* is a label-only line such as ``MISSION``."""
    stripped = line.strip()
    return bool(
        stripped
        and len(stripped) <= 32
        and _LABEL_ONLY_RE.fullmatch(stripped) is not None
    )


def _headline_block(
    body_lines: list[str], *, kicker_text: str
) -> tuple[str, bool, int, int, str | None]:
    """Return ``(headline, truncated, block_start, block_end, label_kicker)``.

    *block_start* and *block_end* are the inclusive and exclusive body-line
    indices of the headline block. *label_kicker* carries an ALL CAPS field
    label when no kicker text exists yet.
    """
    index = 0
    while index < len(body_lines):
        line = body_lines[index]
        if line.strip() and not _is_label_only_line(line):
            break
        index += 1
    if index >= len(body_lines):
        return "", False, len(body_lines), len(body_lines), None
    match = _FIELD_LINE_RE.match(body_lines[index])
    label_kicker: str | None = None
    if match is not None:
        _indent, label, value = match.group(1), match.group(2), match.group(3)
        if not kicker_text and label == label.upper() and label != label.lower():
            label_kicker = " ".join(label.split())
        value_column = match.start(3)
        block_lines = [value]
        end = index + 1
        while end < len(body_lines):
            continuation = body_lines[end]
            if not continuation.strip():
                break
            if _FIELD_LINE_RE.match(continuation) is not None:
                break
            indent = len(continuation) - len(continuation.lstrip())
            if indent < value_column:
                break
            block_lines.append(continuation.strip())
            end += 1
    else:
        block_lines = []
        end = index
        while end < len(body_lines):
            line = body_lines[end]
            if not line.strip():
                break
            if _FIELD_LINE_RE.match(line) is not None:
                break
            block_lines.append(line.strip())
            end += 1
    collapsed = " ".join(" ".join(block_lines).split())
    collapsed = _HEADING_MARKER_RE.sub("", collapsed, count=1).strip()
    truncated = len(collapsed) > _HEADLINE_MAX_CHARS
    return _truncate_headline(collapsed), truncated, index, end, label_kicker


def _truncate_headline(headline: str) -> str:
    """Truncate *headline* to 120 chars at a word boundary with ``…``."""
    if len(headline) <= _HEADLINE_MAX_CHARS:
        return headline
    cut = headline[: _HEADLINE_MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip()
    if not cut:
        cut = headline[: _HEADLINE_MAX_CHARS - 1].rstrip()
    return cut + "…"


def _next_lede(body_lines: list[str], block_end: int) -> tuple[int, int]:
    """Return the ``(start, count)`` of the next 4 non-blank lines."""
    collected: list[int] = []
    index = block_end
    while index < len(body_lines) and len(collected) < 4:
        if body_lines[index].strip():
            collected.append(index)
        index += 1
    if not collected:
        return block_end, 0
    return collected[0], collected[-1] - collected[0] + 1


__all__ = [
    "ClanSummaryLineSpan",
    "TribeClanSummariesSnapshot",
    "TribeClanSummaryEntry",
    "build_tribe_clan_summaries",
    "clan_summaries_signature_for_sources",
    "empty_tribe_clan_summaries_snapshot",
]
