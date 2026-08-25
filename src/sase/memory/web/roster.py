"""Managed strand roster rendering."""

from __future__ import annotations

from sase.agents_sync.rendering_markdown import md_escape
from sase.markdown_width import markdown_print_width
from sase.markdown_wrap import wrap_markdown

from .frontmatter import replace_web_body
from .lookup import ordered_web_strands, strand_glossary_catalog
from .models import MemoryWeb

START_MARKER = "<!-- sase:strands -->"
END_MARKER = "<!-- /sase:strands -->"


def roster_region_error(body: str) -> str | None:
    """Return a managed-region marker error, or ``None``."""

    starts = body.count(START_MARKER)
    ends = body.count(END_MARKER)
    if starts != ends:
        return "memory web strand roster markers are unbalanced"
    if starts > 1:
        return "memory web strand roster markers are duplicated"
    return None


def _inline_entry(keyword: str, display_aliases: tuple[str, ...]) -> str:
    escaped_keyword = md_escape(keyword)
    if not display_aliases:
        return escaped_keyword
    escaped_aliases = ", ".join(md_escape(alias) for alias in display_aliases)
    return f"{escaped_keyword} ({escaped_aliases})"


def render_strand_roster(web: MemoryWeb) -> str:
    """Render the managed roster payload for *web*."""

    strands = ordered_web_strands(web)
    if web.roster == "inline":
        catalog = strand_glossary_catalog(strands)
        entries = "; ".join(
            _inline_entry(strand.keyword, catalog_entry.display_aliases)
            for strand, catalog_entry in zip(strands, catalog.entries, strict=True)
        )
        line = f"**{web.roster_label}:** {entries}".rstrip()
        return wrap_markdown(line, width=markdown_print_width())

    width = markdown_print_width()
    lines: list[str] = []
    for strand in strands:
        summary = strand.summary or ""
        bullet = f"- **{strand.keyword}** (`{strand.slug}`) - {summary}".rstrip()
        lines.append(wrap_markdown(bullet, width=width))
    return "\n".join(lines)


def render_managed_roster_region(web: MemoryWeb) -> str:
    """Render the full managed roster region, including markers."""

    return f"{START_MARKER}\n\n{render_strand_roster(web)}\n\n{END_MARKER}"


def render_web_body_with_roster(web: MemoryWeb) -> tuple[str | None, str | None]:
    """Return the descriptor body with the managed roster inserted or replaced."""

    marker_error = roster_region_error(web.body)
    if marker_error is not None:
        return None, marker_error

    region = render_managed_roster_region(web)
    start = web.body.find(START_MARKER)
    if start < 0:
        base = web.body.rstrip()
        separator = "\n\n" if base else ""
        return f"{base}{separator}{region}\n", None

    end = web.body.find(END_MARKER, start)
    if end < 0:
        return None, "memory web strand roster markers are unbalanced"
    end += len(END_MARKER)
    updated = f"{web.body[:start]}{region}{web.body[end:]}"
    return updated, None


def render_web_descriptor_with_roster(web: MemoryWeb) -> tuple[str | None, str | None]:
    """Return descriptor content with its managed roster region synchronized."""

    body, error = render_web_body_with_roster(web)
    if error is not None or body is None:
        return None, error
    return replace_web_body(web, body), None


__all__ = [
    "END_MARKER",
    "START_MARKER",
    "render_managed_roster_region",
    "render_strand_roster",
    "render_web_body_with_roster",
    "render_web_descriptor_with_roster",
    "roster_region_error",
]
