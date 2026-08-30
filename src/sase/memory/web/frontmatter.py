"""YAML frontmatter parsing for memory-web descriptors and strands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from sase.memory.notes import (
    DEFAULT_MEMORY_LINK_REFERENCE,
    DEFAULT_MEMORY_LINK_RENDERING,
    DEFAULT_MEMORY_PRIORITY,
    MemoryLinkReference,
    MemoryLinkRendering,
    collapse_description,
    normalize_memory_priority,
    parse_memory_link_reference,
    parse_memory_link_rendering,
    render_frontmatter_block,
)
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT

from .models import MemoryStrand, MemoryWeb, WebRosterStyle, WebSource

_SLUG_WORD_RE = re.compile(r"[-_\s]+")
_VALID_ROSTERS: frozenset[str] = frozenset({"inline", "list"})
_VALID_CLOSURES: frozenset[str] = frozenset({"none", "mentions"})
_LINK_REFERENCE_ERROR = "link_reference must be explicit, implicit, or none"
_LINK_RENDERING_ERROR = "link_rendering must be reference or inline"
_CLOSURE_AND_LINK_REFERENCE_ERROR = "cannot declare both closure and link_reference"


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


def _replace_web_body(web: MemoryWeb, body: str) -> str:
    """Return descriptor content with only the body replaced."""

    return f"{web.raw_text[: web.body_start]}{body}"


_TOP_LEVEL_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:")
_WEB_DESCRIPTOR_RETIRED_FRONTMATTER_KEYS = frozenset({"type", "parent"})


def _strip_web_descriptor_retired_frontmatter_keys(raw_frontmatter: str) -> str:
    """Return raw descriptor frontmatter without retired memory-note keys."""
    output: list[str] = []
    skipping_retired_key = False
    for line in raw_frontmatter.splitlines(keepends=True):
        match = _TOP_LEVEL_FRONTMATTER_KEY_RE.match(line)
        if match is not None:
            skipping_retired_key = (
                match.group(1) in _WEB_DESCRIPTOR_RETIRED_FRONTMATTER_KEYS
            )
            if skipping_retired_key:
                continue
        elif skipping_retired_key:
            if line.startswith((" ", "\t")) or not line.strip():
                continue
            skipping_retired_key = False

        output.append(line)
    return "".join(output)


def replace_web_body_with_canonical_frontmatter(web: MemoryWeb, body: str) -> str:
    """Return descriptor content with retired web descriptor frontmatter stripped."""
    parsed = _parse_frontmatter_text(web.raw_text)
    if not parsed.had_frontmatter or parsed.error is not None:
        return _replace_web_body(web, body)

    frontmatter = _strip_web_descriptor_retired_frontmatter_keys(parsed.raw_frontmatter)
    if frontmatter and not frontmatter.endswith(("\n", "\r")):
        frontmatter += "\n"
    return f"---\n{frontmatter}---\n\n{body}"


def slug_to_keyword(slug: str) -> str:
    """Return the default display keyword for a strand slug."""

    words = [part for part in _SLUG_WORD_RE.split(slug.strip()) if part]
    return " ".join(word[:1].upper() + word[1:] for word in words) or slug


def render_strand_frontmatter(
    *,
    keyword: str,
    aliases: Sequence[str] = (),
    summary: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    body: str = "",
    link_reference: MemoryLinkReference | None = None,
    link_rendering: MemoryLinkRendering | None = None,
) -> str:
    """Render one strand file's full content: frontmatter, then *body*.

    Mirrors :func:`sase.memory.notes.apply_memory_frontmatter`'s role for flat
    notes, but for a brand-new strand file rather than an edit of one already
    on disk: there is no prior frontmatter block to preserve, so this simply
    renders a fresh header (via :func:`sase.memory.notes.render_frontmatter_block`,
    which never declares ``type:``/``parent:`` — a strand must not carry
    either) and appends *body* unchanged.
    """

    data: dict[str, Any] = {"keyword": keyword}
    if aliases:
        data["aliases"] = list(aliases)
    if summary is not None:
        data["summary"] = summary
    if link_reference is not None:
        data["link_reference"] = link_reference
    if link_rendering is not None:
        data["link_rendering"] = link_rendering
    if metadata:
        data["metadata"] = dict(metadata)
    return render_frontmatter_block(data) + body.lstrip("\n")


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


def _parse_link_rendering(
    frontmatter: Mapping[str, Any],
    *,
    path: Path,
    default: MemoryLinkRendering = DEFAULT_MEMORY_LINK_RENDERING,
) -> tuple[MemoryLinkRendering | None, str | None]:
    if "link_rendering" not in frontmatter:
        return default, None
    parsed = parse_memory_link_rendering(frontmatter.get("link_rendering"))
    if parsed is None:
        return None, f"{path}: {_LINK_RENDERING_ERROR}"
    return parsed, None


def _parse_descriptor_link_reference(
    frontmatter: Mapping[str, Any], *, path: Path
) -> tuple[MemoryLinkReference | None, str | None]:
    has_closure = "closure" in frontmatter
    has_link_reference = "link_reference" in frontmatter
    if has_closure and has_link_reference:
        return None, f"{path}: {_CLOSURE_AND_LINK_REFERENCE_ERROR}"
    if has_link_reference:
        parsed = parse_memory_link_reference(frontmatter.get("link_reference"))
        if parsed is None:
            return None, f"{path}: {_LINK_REFERENCE_ERROR}"
        return parsed, None
    if has_closure:
        closure = _normalized_scalar(frontmatter.get("closure"))
        if closure not in _VALID_CLOSURES:
            return None, f"{path}: closure must be none or mentions"
        return ("implicit" if closure == "mentions" else "none"), None
    return DEFAULT_MEMORY_LINK_REFERENCE, None


def _parse_strand_link_reference(
    frontmatter: Mapping[str, Any],
    *,
    path: Path,
    default: MemoryLinkReference,
) -> tuple[MemoryLinkReference | None, str | None]:
    if "link_reference" not in frontmatter:
        return default, None
    parsed = parse_memory_link_reference(frontmatter.get("link_reference"))
    if parsed is None:
        return None, f"{path}: {_LINK_REFERENCE_ERROR}"
    return parsed, None


def parse_web_descriptor(
    *,
    root: Path,
    memory_root: Path,
    path: Path,
    text: str | None = None,
    source: WebSource = "file",
) -> tuple[MemoryWeb | None, str | None]:
    """Parse *path* as a web descriptor.

    ``(None, None)`` means the note is not a web descriptor. ``(None, error)`` means
    it tried to declare web metadata but failed validation. Pass *text* to parse
    in-memory content (a :class:`GeneratedMemoryWebProvider` source) instead of
    reading *path* from disk.
    """

    if text is None:
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

    raw_roster = parsed.frontmatter.get("roster", "inline")
    roster = _normalized_scalar(raw_roster)
    if roster not in _VALID_ROSTERS:
        return None, f"{path}: roster must be inline or list"

    link_reference_result, link_reference_error = _parse_descriptor_link_reference(
        parsed.frontmatter, path=path
    )
    if link_reference_error is not None or link_reference_result is None:
        return None, link_reference_error
    link_reference = link_reference_result
    link_rendering, link_rendering_error = _parse_link_rendering(
        parsed.frontmatter, path=path
    )
    if link_rendering_error is not None or link_rendering is None:
        return None, link_rendering_error

    if "priority" in parsed.frontmatter:
        priority, priority_source = normalize_memory_priority(
            parsed.frontmatter["priority"]
        )
        if priority_source == "invalid":
            return None, f"{path}: priority must be a non-negative integer"
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
            description=collapse_description(
                _normalized_scalar(parsed.frontmatter.get("description"))
            ),
            roster=cast(WebRosterStyle, roster),
            roster_label=roster_label,
            strand_noun=strand_noun,
            metadata=metadata,
            body=parsed.body,
            raw_text=text,
            body_start=parsed.body_start,
            frontmatter=dict(parsed.frontmatter),
            priority=priority,
            source=source,
            link_reference=link_reference,
            link_rendering=link_rendering,
        ),
        None,
    )


def parse_memory_strand(
    *,
    root: Path,
    memory_root: Path,
    web_slug: str,
    path: Path,
    text: str | None = None,
    link_reference: MemoryLinkReference = DEFAULT_MEMORY_LINK_REFERENCE,
    link_rendering: MemoryLinkRendering = DEFAULT_MEMORY_LINK_RENDERING,
) -> tuple[MemoryStrand | None, str | None]:
    """Parse one strand file.

    Pass *text* to parse in-memory content instead of reading *path* from disk.
    *link_reference* and *link_rendering* are the owning descriptor's effective
    values; per-strand frontmatter overrides them when present.
    """

    if text is None:
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
    effective_link_reference, link_reference_error = _parse_strand_link_reference(
        parsed.frontmatter, path=path, default=link_reference
    )
    if link_reference_error is not None or effective_link_reference is None:
        return None, link_reference_error
    effective_link_rendering, link_rendering_error = _parse_link_rendering(
        parsed.frontmatter, path=path, default=link_rendering
    )
    if link_rendering_error is not None or effective_link_rendering is None:
        return None, link_rendering_error

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
            body_start=parsed.body_start,
            frontmatter=dict(parsed.frontmatter),
            link_reference=effective_link_reference,
            link_rendering=effective_link_rendering,
        ),
        None,
    )


__all__ = [
    "parse_memory_strand",
    "parse_web_descriptor",
    "render_strand_frontmatter",
    "replace_web_body_with_canonical_frontmatter",
    "slug_to_keyword",
]
