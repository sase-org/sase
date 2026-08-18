"""Structural parsing for AMD-managed ``AGENTS.md`` documents."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re

from ._headings import fence_marker, heading_level
from sase.memory.paths import canonical_memory_reference


_SHORT_SECTION_RE = re.compile(
    r"^##\s+(?:\d+(?:\.\d+)*\.?\s+)?Tier 1 \(short-term\) Memory$"
)
_LONG_SECTION_RE = re.compile(
    r"^##\s+(?:\d+(?:\.\d+)*\.?\s+)?Tier 2 \(long-term\) Memory$"
)
_H2_RE = re.compile(r"^##\s+")
_LEGACY_AMD_COMMENT_RE = re.compile(r"^\s*<!--\s*sase-" r"amd:[^>]+-->\s*$")
_SHORT_MEMORY_BULLET_RE = re.compile(
    r"^- @(?P<path>(?:sase/)?memory/[A-Za-z0-9_.-]+\.md)$"
)
# Inlined short notes render as ``### Title (file)`` headers, optionally
# prefixed as ``### N. Title (file)``; the legacy ``- @memory/<file>.md`` bullet
# form is still recognized for documents generated before short-term memory was
# inlined.
_SHORT_MEMORY_HEADER_RE = re.compile(r"^### (?:.* )?\((?P<name>[A-Za-z0-9_.-]+)\)$")
_LONG_MEMORY_ENTRY_RE = re.compile(
    r"^\*\*`(?P<path>(?:sase/)?memory/[A-Za-z0-9_.-]+\.md)`\*\*(?P<description>.*?)$"
)
_LONG_MEMORY_SECTION_RE = re.compile(
    r"^#{3,4}\s+(?:\d+(?:\.\d+)*\.?\s+)?`(?P<path>(?:sase/)?memory/[A-Za-z0-9_.-]+\.md)`$"
)
_LEGACY_READ_WHEN_SUFFIX_RE = re.compile(r"\s+_Read when\b.*?_$")


@dataclass(frozen=True)
class _AmdLongMemoryEntry:
    """One long-memory entry parsed from a managed or legacy AGENTS.md."""

    path: str
    description: str


@dataclass(frozen=True)
class _AmdAgentsDocument:
    """Parsed AMD memory structure from an ``AGENTS.md`` document."""

    has_short_section: bool
    has_long_section: bool
    short_memory_paths: tuple[str, ...]
    long_memory_entries: tuple[_AmdLongMemoryEntry, ...]

    @property
    def has_memory_structure(self) -> bool:
        return self.has_short_section or self.has_long_section


def _normalized_line(line: str) -> str:
    return " ".join(line.strip().split())


def _normalized_description_lines(lines: Iterable[str]) -> str:
    normalized_lines = [_normalized_line(line) for line in lines]
    while normalized_lines and not normalized_lines[0]:
        normalized_lines.pop(0)
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()
    if not normalized_lines:
        return ""

    collapsed_lines: list[str] = []
    previous_blank = False
    for line in normalized_lines:
        if not line:
            if previous_blank:
                continue
            previous_blank = True
        else:
            previous_blank = False
        collapsed_lines.append(line)
    return "\n".join(collapsed_lines)


def normalize_long_memory_description_lines(lines: Iterable[str]) -> str:
    """Normalize an AGENTS.md long-memory description without flattening it."""
    normalized = _normalized_description_lines(lines)
    if not normalized:
        return ""
    description_lines = normalized.splitlines()
    description_lines[-1] = _LEGACY_READ_WHEN_SUFFIX_RE.sub(
        "", description_lines[-1]
    ).strip()
    return _normalized_description_lines(description_lines)


def _is_legacy_amd_comment(line: str) -> bool:
    return _LEGACY_AMD_COMMENT_RE.match(line) is not None


def _section_bounds(
    lines: list[str],
    heading_re: re.Pattern[str],
) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        if heading_re.match(_normalized_line(line)) is None:
            continue
        end = len(lines)
        for section_end, candidate in enumerate(lines[index + 1 :], start=index + 1):
            if _H2_RE.match(candidate):
                end = section_end
                break
        return index + 1, end
    return None


def _short_memory_paths(
    lines: list[str], bounds: tuple[int, int] | None
) -> tuple[str, ...]:
    if bounds is None:
        return ()
    start, end = bounds
    paths: list[str] = []
    for raw_line in lines[start:end]:
        if _is_legacy_amd_comment(raw_line):
            continue
        if raw_line[: len(raw_line) - len(raw_line.lstrip())]:
            continue
        normalized = _normalized_line(raw_line)
        bullet_match = _SHORT_MEMORY_BULLET_RE.match(normalized)
        if bullet_match is not None:
            paths.append(
                canonical_memory_reference(bullet_match.group("path")).as_posix()
            )
            continue
        header_match = _SHORT_MEMORY_HEADER_RE.match(normalized)
        if header_match is not None:
            paths.append(f"sase/memory/{header_match.group('name')}.md")
    return tuple(paths)


def _description_text(lines: list[str]) -> str:
    return normalize_long_memory_description_lines(lines)


def long_memory_entry_path(line: str) -> str | None:
    """Return the canonical path if *line* starts a long-memory entry."""
    stripped = line.strip()
    section_match = _LONG_MEMORY_SECTION_RE.match(stripped)
    if section_match is not None:
        return canonical_memory_reference(section_match.group("path")).as_posix()
    legacy_match = _LONG_MEMORY_ENTRY_RE.match(stripped)
    if legacy_match is not None:
        return canonical_memory_reference(legacy_match.group("path")).as_posix()
    return None


def _legacy_long_memory_inline_description(line: str) -> str:
    match = _LONG_MEMORY_ENTRY_RE.match(line.strip())
    if match is None:
        return ""
    return match.group("description").strip()


def collect_long_memory_entries(
    lines: list[str],
    start: int,
    end: int,
) -> tuple[_AmdLongMemoryEntry, ...]:
    """Parse long-memory entries from ``lines[start:end]``.

    Description collection stops at the next long-memory entry or at any
    unfenced heading that is not itself an entry, so a trailing
    ``### Glossary Terms`` section is not absorbed. Headings inside fenced
    code blocks stay part of the description.
    """
    entries: list[_AmdLongMemoryEntry] = []
    index = start
    while index < end:
        raw_line = lines[index]
        if _is_legacy_amd_comment(raw_line) or not raw_line.strip():
            index += 1
            continue

        path = long_memory_entry_path(raw_line)
        if path is None:
            index += 1
            continue

        description_lines: list[str] = []
        inline_description = _legacy_long_memory_inline_description(raw_line)
        if inline_description:
            description_lines.append(inline_description)
        index += 1

        in_fence = False
        active_fence_marker = ""
        while index < end:
            candidate = lines[index]
            if _is_legacy_amd_comment(candidate):
                index += 1
                continue
            marker = fence_marker(candidate)
            if in_fence:
                description_lines.append(candidate)
                if marker == active_fence_marker:
                    in_fence = False
                index += 1
                continue
            if marker is not None:
                in_fence = True
                active_fence_marker = marker
                description_lines.append(candidate)
                index += 1
                continue
            if long_memory_entry_path(candidate) is not None:
                break
            if heading_level(candidate) is not None:
                break
            description_lines.append(candidate)
            index += 1

        entries.append(
            _AmdLongMemoryEntry(
                path=path,
                description=_description_text(description_lines),
            )
        )
    return tuple(entries)


def _long_memory_entries(
    lines: list[str],
    bounds: tuple[int, int] | None,
) -> tuple[_AmdLongMemoryEntry, ...]:
    if bounds is None:
        return ()
    start, end = bounds
    return collect_long_memory_entries(lines, start, end)


def parse_amd_agents_document(text: str | None) -> _AmdAgentsDocument:
    """Parse AMD memory sections from an ``AGENTS.md`` document."""
    if text is None:
        return _AmdAgentsDocument(
            has_short_section=False,
            has_long_section=False,
            short_memory_paths=(),
            long_memory_entries=(),
        )

    lines = text.splitlines()
    short_bounds = _section_bounds(lines, _SHORT_SECTION_RE)
    long_bounds = _section_bounds(lines, _LONG_SECTION_RE)
    return _AmdAgentsDocument(
        has_short_section=short_bounds is not None,
        has_long_section=long_bounds is not None,
        short_memory_paths=_short_memory_paths(lines, short_bounds),
        long_memory_entries=_long_memory_entries(lines, long_bounds),
    )


__all__ = [
    "collect_long_memory_entries",
    "long_memory_entry_path",
    "normalize_long_memory_description_lines",
    "parse_amd_agents_document",
]
