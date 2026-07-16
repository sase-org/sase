"""Structural parsing for AMD-managed ``AGENTS.md`` documents."""

from __future__ import annotations

from dataclasses import dataclass
import re

from sase.memory.paths import canonical_memory_reference


_SHORT_SECTION_HEADINGS = frozenset(
    {
        "## Tier 1 (short-term) Memory",
    }
)
_LONG_SECTION_HEADINGS = frozenset(
    {
        "## Tier 2 (long-term) Memory",
    }
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


@dataclass(frozen=True)
class _AmdLongMemoryEntry:
    """One long-memory entry in AMD's visible description-list shape."""

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


def _is_legacy_amd_comment(line: str) -> bool:
    return _LEGACY_AMD_COMMENT_RE.match(line) is not None


def _section_bounds(
    lines: list[str],
    headings: frozenset[str],
) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        if _normalized_line(line) not in headings:
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
    body = " ".join(line.strip() for line in lines)
    body = " ".join(body.split())
    return re.sub(r"\s+_Read when\b.*?_$", "", body).strip()


def _long_memory_entries(
    lines: list[str],
    bounds: tuple[int, int] | None,
) -> tuple[_AmdLongMemoryEntry, ...]:
    if bounds is None:
        return ()

    entries: list[_AmdLongMemoryEntry] = []
    index, end = bounds
    while index < end:
        raw_line = lines[index]
        if _is_legacy_amd_comment(raw_line) or not raw_line.strip():
            index += 1
            continue

        match = _LONG_MEMORY_ENTRY_RE.match(raw_line.strip())
        if match is None:
            index += 1
            continue

        description_lines: list[str] = []
        inline_description = match.group("description").strip()
        if inline_description:
            description_lines.append(inline_description)
        index += 1

        while index < end:
            candidate = lines[index]
            if _is_legacy_amd_comment(candidate):
                index += 1
                continue
            if not candidate.strip():
                break
            if _LONG_MEMORY_ENTRY_RE.match(candidate.strip()) is not None:
                break
            description_lines.append(candidate)
            index += 1

        entries.append(
            _AmdLongMemoryEntry(
                path=canonical_memory_reference(match.group("path")).as_posix(),
                description=_description_text(description_lines),
            )
        )
    return tuple(entries)


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
    short_bounds = _section_bounds(lines, _SHORT_SECTION_HEADINGS)
    long_bounds = _section_bounds(lines, _LONG_SECTION_HEADINGS)
    return _AmdAgentsDocument(
        has_short_section=short_bounds is not None,
        has_long_section=long_bounds is not None,
        short_memory_paths=_short_memory_paths(lines, short_bounds),
        long_memory_entries=_long_memory_entries(lines, long_bounds),
    )


__all__ = [
    "parse_amd_agents_document",
]
