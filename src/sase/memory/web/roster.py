"""Managed strand roster rendering."""

from __future__ import annotations

from .frontmatter import replace_web_body
from .lookup import normalize_memory_web_reference
from .models import MemoryStrand, MemoryWeb

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


def _ordered_strands(web: MemoryWeb) -> tuple[MemoryStrand, ...]:
    return tuple(
        sorted(
            web.strands,
            key=lambda strand: (
                normalize_memory_web_reference(strand.keyword),
                strand.slug,
            ),
        )
    )


def _inline_entry(strand: MemoryStrand) -> str:
    if not strand.aliases:
        return strand.keyword
    aliases = ", ".join(strand.aliases)
    return f"{strand.keyword} ({aliases})"


def render_strand_roster(web: MemoryWeb) -> str:
    """Render the managed roster payload for *web*."""

    strands = _ordered_strands(web)
    if web.roster == "inline":
        entries = "; ".join(_inline_entry(strand) for strand in strands)
        return f"**{web.roster_label}:** {entries}".rstrip()

    lines: list[str] = []
    for strand in strands:
        summary = strand.summary or ""
        lines.append(f"- **{strand.keyword}** (`{strand.slug}`) - {summary}".rstrip())
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
