"""YAML frontmatter parsing for memory-web descriptors and strands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]

from sase.memory.notes import (
    DEFAULT_MEMORY_PRIORITY,
    collapse_description,
    normalize_memory_priority,
    normalize_memory_note_type,
)
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT

from .models import MemoryStrand, MemoryWeb, WebClosureMode, WebRosterStyle

_SLUG_WORD_RE = re.compile(r"[-_\s]+")
_VALID_ROSTERS: frozenset[str] = frozenset({"inline", "list"})
_VALID_CLOSURES: frozenset[str] = frozenset({"none", "mentions"})


@dataclass(frozen=True)
class _ParsedFrontmatter:
    frontmatter: dict[str, Any]
    body: str
    body_start: int
    raw_frontmatter: str
    error: str | None = None
    had_frontmatter: bool = False


def _parse_frontmatter_text(text: str) -> _ParsedFrontmatter:
    """Parse a Markdown frontmatter block while preserving body offsets."""

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return _ParsedFrontmatter(
            frontmatter={},
            body=text,
            body_start=0,
            raw_frontmatter="",
            had_frontmatter=False,
        )

    offset = len(lines[0])
    close_start: int | None = None
    close_end: int | None = None
    for line in lines[1:]:
        line_start = offset
        offset += len(line)
        if line.strip() == "---":
            close_start = line_start
            close_end = offset
            break

    if close_start is None or close_end is None:
        return _ParsedFrontmatter(
            frontmatter={},
            body="",
            body_start=len(text),
            raw_frontmatter=text[len(lines[0]) :],
            error="frontmatter block is missing closing --- marker",
            had_frontmatter=True,
        )

    raw_frontmatter = text[len(lines[0]) : close_start]
    body_start = close_end
    if text[body_start : body_start + 1] == "\n":
        body_start += 1
    body = text[body_start:]
    try:
        loaded = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        return _ParsedFrontmatter(
            frontmatter={},
            body=body,
            body_start=body_start,
            raw_frontmatter=raw_frontmatter,
            error=f"malformed YAML frontmatter: {exc}",
            had_frontmatter=True,
        )
    if not isinstance(loaded, dict):
        return _ParsedFrontmatter(
            frontmatter={},
            body=body,
            body_start=body_start,
            raw_frontmatter=raw_frontmatter,
            error="frontmatter must be a mapping",
            had_frontmatter=True,
        )
    frontmatter = {key: value for key, value in loaded.items() if isinstance(key, str)}
    return _ParsedFrontmatter(
        frontmatter=frontmatter,
        body=body,
        body_start=body_start,
        raw_frontmatter=raw_frontmatter,
        had_frontmatter=True,
    )


def _raw_frontmatter_mentions_key(parsed: _ParsedFrontmatter, key: str) -> bool:
    """Return true when a malformed block appears to mention *key*."""

    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*:")
    return bool(pattern.search(parsed.raw_frontmatter))


def replace_web_body(web: MemoryWeb, body: str) -> str:
    """Return descriptor content with only the body replaced."""

    return f"{web.raw_text[: web.body_start]}{body}"


def slug_to_keyword(slug: str) -> str:
    """Return the default display keyword for a strand slug."""

    words = [part for part in _SLUG_WORD_RE.split(slug.strip()) if part]
    return " ".join(word[:1].upper() + word[1:] for word in words) or slug


def _default_roster_label(strand_noun: str) -> str:
    """Derive the default roster label from the configured display noun."""

    words = " ".join(strand_noun.split()).upper()
    suffix = "" if words.endswith("S") else "S"
    return f"{words}{suffix}"


def _normalized_scalar(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _metadata(value: Any, *, path: Path) -> tuple[dict[str, Any], str | None]:
    if value is None:
        return {}, None
    if not isinstance(value, dict):
        return {}, f"{path}: metadata must be a mapping"
    return dict(value), None


def _aliases(value: Any, *, path: Path) -> tuple[tuple[str, ...], str | None]:
    if value is None:
        return (), None
    if not isinstance(value, list):
        return (), f"{path}: aliases must be a list of strings"
    aliases: list[str] = []
    for item in value:
        alias = _normalized_scalar(item)
        if alias is None:
            return (), f"{path}: aliases must be a list of strings"
        aliases.append(alias)
    return tuple(aliases), None


def parse_web_descriptor(
    *,
    root: Path,
    memory_root: Path,
    path: Path,
) -> tuple[MemoryWeb | None, str | None]:
    """Parse *path* as a web descriptor.

    ``(None, None)`` means the note is not a web descriptor. ``(None, error)`` means
    it tried to declare web metadata but failed validation.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path}: failed to read memory web descriptor: {exc}"

    parsed = _parse_frontmatter_text(text)
    if parsed.error is not None:
        if _raw_frontmatter_mentions_key(parsed, "web"):
            return None, f"{path}: {parsed.error}"
        return None, None

    raw_web = parsed.frontmatter.get("web")
    if raw_web is None:
        return None, None
    if not isinstance(raw_web, bool):
        return None, f"{path}: web must be a boolean"
    if raw_web is not True:
        return None, None

    raw_type = _normalized_scalar(parsed.frontmatter.get("type"))
    rendering_type = normalize_memory_note_type(raw_type)
    if rendering_type not in {"core", "reference"}:
        return None, f"{path}: web descriptor type must be core or reference"

    raw_roster = parsed.frontmatter.get("roster", "inline")
    roster = _normalized_scalar(raw_roster)
    if roster not in _VALID_ROSTERS:
        return None, f"{path}: roster must be inline or list"

    raw_closure = parsed.frontmatter.get("closure", "none")
    closure = _normalized_scalar(raw_closure)
    if closure not in _VALID_CLOSURES:
        return None, f"{path}: closure must be none or mentions"

    if "priority" in parsed.frontmatter:
        priority, priority_source = normalize_memory_priority(
            parsed.frontmatter["priority"]
        )
        if priority_source == "invalid":
            return None, f"{path}: priority must be a non-negative integer"
        if rendering_type == "reference":
            return None, f"{path}: priority is only meaningful on core memory webs"
    else:
        priority = DEFAULT_MEMORY_PRIORITY

    strand_noun = _normalized_scalar(parsed.frontmatter.get("strand_noun")) or "strand"
    roster_label = _normalized_scalar(
        parsed.frontmatter.get("roster_label")
    ) or _default_roster_label(strand_noun)
    metadata, metadata_error = _metadata(parsed.frontmatter.get("metadata"), path=path)
    if metadata_error is not None:
        return None, metadata_error

    relative = CANONICAL_MEMORY_RELATIVE_ROOT / f"{path.stem}.md"
    return (
        MemoryWeb(
            root=root,
            memory_root=memory_root,
            slug=path.stem,
            path=path,
            relative_path=relative.as_posix(),
            rendering_type=cast(Literal["core", "reference"], rendering_type),
            description=collapse_description(
                _normalized_scalar(parsed.frontmatter.get("description"))
            ),
            roster=cast(WebRosterStyle, roster),
            roster_label=roster_label,
            strand_noun=strand_noun,
            closure=cast(WebClosureMode, closure),
            metadata=metadata,
            body=parsed.body,
            raw_text=text,
            body_start=parsed.body_start,
            frontmatter=dict(parsed.frontmatter),
            priority=priority,
        ),
        None,
    )


def parse_memory_strand(
    *,
    root: Path,
    memory_root: Path,
    web_slug: str,
    path: Path,
) -> tuple[MemoryStrand | None, str | None]:
    """Parse one strand file."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path}: failed to read memory strand: {exc}"

    parsed = _parse_frontmatter_text(text)
    if parsed.error is not None:
        return None, f"{path}: {parsed.error}"

    if "type" in parsed.frontmatter:
        return None, f"{path}: memory strands must not declare type"
    if "parent" in parsed.frontmatter:
        return None, f"{path}: memory strands must not declare parent"

    keyword = _normalized_scalar(parsed.frontmatter.get("keyword")) or slug_to_keyword(
        path.stem
    )
    aliases, aliases_error = _aliases(parsed.frontmatter.get("aliases"), path=path)
    if aliases_error is not None:
        return None, aliases_error
    summary = _normalized_scalar(parsed.frontmatter.get("summary"))
    if "summary" in parsed.frontmatter and summary is None:
        return None, f"{path}: summary must be a non-empty string"
    metadata, metadata_error = _metadata(parsed.frontmatter.get("metadata"), path=path)
    if metadata_error is not None:
        return None, metadata_error

    relative = CANONICAL_MEMORY_RELATIVE_ROOT / web_slug / path.name
    return (
        MemoryStrand(
            root=root,
            memory_root=memory_root,
            web_slug=web_slug,
            slug=path.stem,
            path=path,
            relative_path=relative.as_posix(),
            keyword=keyword,
            aliases=aliases,
            summary=summary,
            metadata=metadata,
            body=parsed.body,
            raw_text=text,
            frontmatter=dict(parsed.frontmatter),
        ),
        None,
    )


__all__ = [
    "parse_memory_strand",
    "parse_web_descriptor",
    "replace_web_body",
    "slug_to_keyword",
]
