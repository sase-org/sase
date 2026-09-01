"""Managed strand roster rendering."""

from __future__ import annotations

from sase.agents_sync.rendering_markdown import md_escape
from sase.markdown_width import markdown_print_width
from sase.markdown_wrap import wrap_markdown

from .frontmatter import replace_web_body_with_canonical_frontmatter
from .lookup import ordered_web_strands, strand_glossary_catalog
from .models import MemoryWeb
from .supersession import (
    StrandSupersession,
    format_inline_roster_supersession_suffix,
    format_roster_supersession_marker,
    parse_strand_supersession,
)

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


def strip_managed_roster_markers(body: str) -> str:
    """Return *body* with roster marker lines and their preceding blanks removed.

    Marker detection intentionally does not track Markdown code fences:
    ``roster_region_error`` already treats exact marker lines anywhere in the
    body as the managed roster region, fenced or not.
    """

    has_final_newline = body.endswith(("\n", "\r"))
    lines = body.splitlines(keepends=True)
    if not any(line.strip() in {START_MARKER, END_MARKER} for line in lines):
        return body

    output: list[str] = []
    for line in lines:
        if line.strip() in {START_MARKER, END_MARKER}:
            while output and not output[-1].strip():
                output.pop()
            continue
        output.append(line)
    stripped = "".join(output)
    if not has_final_newline:
        if stripped.endswith("\r\n"):
            return stripped[:-2]
        if stripped.endswith(("\n", "\r")):
            return stripped[:-1]
    return stripped


def _inline_entry(
    keyword: str,
    display_aliases: tuple[str, ...],
    supersession: StrandSupersession | None = None,
) -> str:
    escaped_keyword = md_escape(keyword)
    if not display_aliases:
        entry = escaped_keyword
    else:
        escaped_aliases = ", ".join(md_escape(alias) for alias in display_aliases)
        entry = f"{escaped_keyword} ({escaped_aliases})"
    if supersession is None:
        return entry
    return f"{entry} {format_inline_roster_supersession_suffix(supersession)}"


def render_strand_roster(web: MemoryWeb) -> str:
    """Render the managed roster payload for *web*."""

    strands = ordered_web_strands(web)
    if web.roster == "inline":
        catalog = strand_glossary_catalog(strands)
        entries = "; ".join(
            _inline_entry(
                strand.keyword,
                catalog_entry.display_aliases,
                parse_strand_supersession(strand),
            )
            for strand, catalog_entry in zip(strands, catalog.entries, strict=True)
        )
        line = f"**{web.roster_label}:** {entries}".rstrip()
        return wrap_markdown(line, width=markdown_print_width())

    width = markdown_print_width()
    lines: list[str] = []
    for strand in strands:
        summary = strand.summary or ""
        supersession = parse_strand_supersession(strand)
        if supersession is None:
            bullet = f"- **{strand.keyword}** (`{strand.slug}`) - {summary}".rstrip()
        else:
            marker = format_roster_supersession_marker(supersession, web_slug=web.slug)
            bullet = (
                f"- **{strand.keyword}** (`{strand.slug}`) - {marker} {summary}"
            ).rstrip()
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
    return replace_web_body_with_canonical_frontmatter(web, body), None


__all__ = [
    "END_MARKER",
    "START_MARKER",
    "render_managed_roster_region",
    "render_strand_roster",
    "render_web_body_with_roster",
    "render_web_descriptor_with_roster",
    "roster_region_error",
    "strip_managed_roster_markers",
]
