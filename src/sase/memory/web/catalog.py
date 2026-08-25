"""Glossary catalog helpers for memory-web-backed sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.content_layout_wire import LayoutCollisionError
from sase.core.glossary_facade import GlossaryInputEntry, GlossarySource

from .discovery import discover_memory_webs
from .lookup import ordered_web_strands
from .models import MemoryStrand, MemoryWeb

GLOSSARY_WEB_SLUG = "glossary"
GLOSSARY_MIGRATE_HINT = "sase memory web migrate glossary"


@dataclass(frozen=True, slots=True)
class _MemoryWebSourceSignature:
    """Filesystem signature over a web descriptor and its strand files."""

    path: str
    mtime_ns: int
    size: int


def find_memory_web(root: Path, slug: str) -> MemoryWeb | None:
    """Return the discovered web named *slug* under *root*, if any.

    A canonical/legacy memory-root layout collision is reported elsewhere
    (memory migration planning); here it just means no web can be resolved.
    """

    try:
        discovery = discover_memory_webs(root)
    except LayoutCollisionError:
        return None
    for web in discovery.webs:
        if web.slug == slug:
            return web
    return None


def glossary_dual_source_diagnostic(
    *, has_web: bool, config_declared: bool
) -> str | None:
    """Return the one fail-closed message when both glossary sources exist.

    A project's glossary comes from strand files if a ``glossary`` web
    exists, and from ``memory.glossary`` if it does not. Both present is a
    blocker, never a merge and never a silent preference.
    """

    if has_web and config_declared:
        return (
            "glossary is declared in both a `glossary` memory web and "
            f"`memory.glossary`; run `{GLOSSARY_MIGRATE_HINT}` to finish migrating "
            "before either can be read"
        )
    return None


def memory_web_source_signature(web: MemoryWeb) -> _MemoryWebSourceSignature:
    """Return a signature over *web*'s descriptor and every strand file.

    ``mtime_ns`` is the maximum modification time and ``size`` is the summed
    byte size across the descriptor plus every strand, so a strand edit, add,
    or removal always changes the signature.
    """

    strand_dir = web.memory_root / web.slug
    mtime_ns = 0
    size = 0
    for path in (web.path, *(strand.path for strand in web.strands)):
        try:
            stat = path.stat()
        except OSError:
            continue
        mtime_ns = max(mtime_ns, stat.st_mtime_ns)
        size += stat.st_size
    return _MemoryWebSourceSignature(path=str(strand_dir), mtime_ns=mtime_ns, size=size)


def memory_web_glossary_entries(web: MemoryWeb) -> tuple[GlossaryInputEntry, ...]:
    """Return one :class:`GlossaryInputEntry` per strand, in roster order."""

    return tuple(
        GlossaryInputEntry(
            term=strand.keyword,
            definition=strand.body,
            aliases=strand.aliases,
            source=GlossarySource(
                source_path=str(strand.path),
                keyword_range=_strand_keyword_range(strand),
                body_range=_strand_body_range(strand),
            ),
        )
        for strand in ordered_web_strands(web)
    )


def _position(text: str, offset: int) -> dict[str, int]:
    offset = max(0, min(offset, len(text)))
    line_start = text.rfind("\n", 0, offset) + 1
    return {"line": text.count("\n", 0, offset), "character": offset - line_start}


def _range(text: str, start: int, end: int) -> dict[str, Any]:
    return {"start": _position(text, start), "end": _position(text, end)}


def _strand_keyword_range(strand: MemoryStrand) -> dict[str, Any]:
    frontmatter_text = strand.raw_text[: strand.body_start]
    for line_start, line in _line_offsets(frontmatter_text):
        if not line.startswith("keyword:"):
            continue
        value = line[len("keyword:") :]
        value_start = line_start + len("keyword:") + (len(value) - len(value.lstrip()))
        value_end = line_start + len(line.rstrip())
        return _range(strand.raw_text, value_start, max(value_start, value_end))
    first_line = strand.body.splitlines()[0] if strand.body.splitlines() else ""
    return _range(
        strand.raw_text,
        strand.body_start,
        strand.body_start + len(first_line),
    )


def _strand_body_range(strand: MemoryStrand) -> dict[str, Any]:
    return _range(strand.raw_text, strand.body_start, len(strand.raw_text))


def _line_offsets(text: str) -> list[tuple[int, str]]:
    offsets: list[tuple[int, str]] = []
    offset = 0
    for line in text.splitlines():
        offsets.append((offset, line))
        offset += len(line) + 1
    return offsets


def glossary_source_from_wire(payload: object) -> GlossarySource | None:
    """Return source metadata from either v1 or v2 glossary source wire keys."""

    if not isinstance(payload, Mapping):
        return None

    source_path = _string_value(payload.get("source_path"))
    if source_path is None:
        source_path = _string_value(payload.get("config_path"))

    key_path = _string_tuple(payload.get("key_path"))
    if not key_path:
        key_path = _string_tuple(payload.get("config_key_path"))

    keyword_range = _range_payload(payload.get("keyword_range"))
    if keyword_range is None:
        keyword_range = _range_payload(payload.get("term_range"))

    body_range = _range_payload(payload.get("body_range"))
    if body_range is None:
        body_range = _range_payload(payload.get("definition_range"))

    aliases_range = _range_payload(payload.get("aliases_range"))

    if (
        source_path is None
        and not key_path
        and keyword_range is None
        and body_range is None
        and aliases_range is None
    ):
        return None

    return GlossarySource(
        source_path=source_path,
        key_path=key_path,
        keyword_range=keyword_range,
        body_range=body_range,
        aliases_range=aliases_range,
    )


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _range_payload(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


__all__ = [
    "GLOSSARY_MIGRATE_HINT",
    "GLOSSARY_WEB_SLUG",
    "find_memory_web",
    "glossary_dual_source_diagnostic",
    "glossary_source_from_wire",
    "memory_web_glossary_entries",
    "memory_web_source_signature",
]
