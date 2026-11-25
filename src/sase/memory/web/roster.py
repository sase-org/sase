"""Managed strand roster rendering."""

from __future__ import annotations

from typing import Literal

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

#: Compile-time list-roster compaction styles. ``"superseded"`` renders
#: superseded entries as one line with no summary; ``"all"`` renders every
#: entry as number, title, and slug only. Inline rosters ignore compaction.
RosterCompaction = Literal["superseded", "all"]


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


def _list_entry(
    number: int, keyword: str, slug: str, detail: str, *, width: int
) -> str:
    prefix = f"{number}. **{keyword}** (`{slug}`)"
    inline = f"{prefix} - {detail}".rstrip()

    if "\n" in wrap_markdown(prefix, width=width):
        return wrap_markdown(inline, width=width)

    detail_prefix = " " * len(f"{number}. ")
    detail_lines = wrap_markdown(f"{detail_prefix}- {detail}", width=width)
    return f"{prefix}\n{detail_lines}"


def _compact_list_entry(
    number: int, keyword: str, slug: str, marker: str | None, *, width: int
) -> str:
    entry = f"{number}. **{keyword}** (`{slug}`)"
    if marker is not None:
        entry = f"{entry} {marker}"
    return wrap_markdown(entry, width=width)


def _roster_compaction_note(web_slug: str, compaction: RosterCompaction) -> str:
    """Return the one-line note ending a compacted list roster."""

    omitted = (
        "Summaries of superseded entries"
        if compaction == "superseded"
        else "Entry summaries"
    )
    return (
        f"_{omitted} omitted to fit the provider budget; read one with "
        f"`sase memory read {web_slug}:<keyword>`._"
    )


def render_strand_roster(
    web: MemoryWeb, *, compaction: RosterCompaction | None = None
) -> str:
    """Render the managed roster payload for *web*.

    *compaction* selects a compile-time compact list style (see
    :data:`RosterCompaction`); it never reaches a descriptor on disk. A
    compacted roster ends with a one-line omission note when at least
    one entry was compacted, and is otherwise byte-identical to the default.
    """

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
    compacted = False
    for number, strand in enumerate(strands, start=1):
        summary = strand.summary or ""
        supersession = parse_strand_supersession(strand)
        marker = (
            None
            if supersession is None
            else format_roster_supersession_marker(supersession, web_slug=web.slug)
        )
        if compaction == "all" or (
            compaction == "superseded" and supersession is not None
        ):
            compacted = True
            lines.append(
                _compact_list_entry(
                    number,
                    strand.keyword,
                    strand.slug,
                    None if compaction == "all" else marker,
                    width=width,
                )
            )
            continue
        detail = summary if marker is None else f"{marker} {summary}"
        lines.append(
            _list_entry(number, strand.keyword, strand.slug, detail, width=width)
        )
    if compacted and compaction is not None:
        lines.extend(("", _roster_compaction_note(web.slug, compaction)))
    return "\n".join(lines)


def render_managed_roster_region(
    web: MemoryWeb, *, compaction: RosterCompaction | None = None
) -> str:
    """Render the full managed roster region, including markers."""

    roster = render_strand_roster(web, compaction=compaction)
    return f"{START_MARKER}\n\n{roster}\n\n{END_MARKER}"


def render_web_body_with_roster(
    web: MemoryWeb, *, compaction: RosterCompaction | None = None
) -> tuple[str | None, str | None]:
    """Return the descriptor body with the managed roster inserted or replaced.

    *compaction* is the compile-time compact list style; descriptor writers
    (:func:`render_web_descriptor_with_roster`) always use the default.
    """

    marker_error = roster_region_error(web.body)
    if marker_error is not None:
        return None, marker_error

    region = render_managed_roster_region(web, compaction=compaction)
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


def _counted_strand_noun(noun: str, count: int) -> str:
    if count == 1:
        return noun
    if noun.endswith("s"):
        return noun
    return f"{noun}s"


def render_on_demand_roster_pointer(web: MemoryWeb) -> str:
    """Return the generated on-demand roster pointer for *web*.

    The pointer never names a specific web slug in code; it uses *web*'s
    ``slug``, ``roster_label``, ``strand_noun``, and ``roster_read_when``.
    """

    count = len(ordered_web_strands(web))
    noun = _counted_strand_noun(web.strand_noun, count)
    verb = "is" if count == 1 else "are"
    command = f'`sase memory read roster:{web.slug} -r "<why>"`'
    strand_command = f'`sase memory read {web.slug}:<keyword> -r "<why>"`'
    lead = f"**Roster on demand.** This web's {count} {noun} {verb} not listed here."
    if web.roster_read_when:
        instruction = f"You MUST read the {web.roster_label} roster with {command}:"
        bullets = "\n".join(f"- {trigger}" for trigger in web.roster_read_when)
        body = f"{lead} {instruction}\n\n{bullets}"
    else:
        instruction = (
            f"Read the {web.roster_label} roster with {command} when you need one."
        )
        body = f"{lead} {instruction}"
    footer = f"Read one {web.strand_noun} with {strand_command}."
    return wrap_markdown(f"{body}\n\n{footer}", width=markdown_print_width())


def render_web_projection_body(
    web: MemoryWeb, *, compaction: RosterCompaction | None = None
) -> tuple[str | None, str | None]:
    """Return the instruction-projection body for *web*.

    For ``always`` webs this is exactly
    ``strip_managed_roster_markers(render_web_body_with_roster(...))``.
    For ``on_demand`` webs the managed roster region is replaced by
    :func:`render_on_demand_roster_pointer`; the pointer is appended where
    the roster would go when the markers are absent. Descriptor writers
    still use :func:`render_web_descriptor_with_roster`, so the on-disk
    region stays full.
    """

    if web.roster_loading != "on_demand":
        body, error = render_web_body_with_roster(web, compaction=compaction)
        if error is not None or body is None:
            return None, error
        return strip_managed_roster_markers(body), None

    marker_error = roster_region_error(web.body)
    if marker_error is not None:
        return None, marker_error

    pointer = render_on_demand_roster_pointer(web)
    start = web.body.find(START_MARKER)
    if start < 0:
        base = web.body.rstrip()
        separator = "\n\n" if base else ""
        return f"{base}{separator}{pointer}\n", None

    end = web.body.find(END_MARKER, start)
    if end < 0:
        return None, "memory web strand roster markers are unbalanced"
    end += len(END_MARKER)
    return f"{web.body[:start]}{pointer}{web.body[end:]}", None


__all__ = [
    "END_MARKER",
    "START_MARKER",
    "RosterCompaction",
    "render_managed_roster_region",
    "render_on_demand_roster_pointer",
    "render_strand_roster",
    "render_web_body_with_roster",
    "render_web_descriptor_with_roster",
    "render_web_projection_body",
    "roster_region_error",
    "strip_managed_roster_markers",
]
