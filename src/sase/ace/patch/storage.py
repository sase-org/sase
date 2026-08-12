"""ProjectSpec Patch storage spelling helpers."""

from __future__ import annotations

import re

CANONICAL_PATCH_HEADING = "## Patch"
LEGACY_PATCH_HEADING = "## ChangeSpec"
DEFAULT_STITCH_SECTION_HEADER = "STITCHES:"
LEGACY_STITCH_SECTION_HEADER = "COMMITS:"
STITCH_SECTION_HEADERS = (
    DEFAULT_STITCH_SECTION_HEADER,
    LEGACY_STITCH_SECTION_HEADER,
)

_PATCH_HEADING_RE = re.compile(
    r"^##\s+(?:Patch|ChangeSpec)\b"
)  # legacy compatibility alias


def is_patch_heading(line: str) -> bool:
    """Return True when *line* starts a canonical or legacy Patch record."""
    return bool(_PATCH_HEADING_RE.match(line.strip()))


def is_record_separator_line(line: str) -> bool:
    """Return True when *line* counts toward the record terminator."""
    return line.rstrip("\r\n") == ""


def is_stitch_section_header(line: str) -> bool:
    """Return True for canonical or legacy stitch-history section headers."""
    return line.startswith(STITCH_SECTION_HEADERS)


def stitch_section_header_for(line: str) -> str | None:
    """Return the normalized stitch-history header from *line*, if present."""
    stripped = line.strip()
    if stripped in STITCH_SECTION_HEADERS:
        return stripped
    return None


def format_patch_block(
    *,
    name: str,
    description: str,
    parent: str | None = None,
    pr_url: str | None = None,
    pr_origin: str | None = None,
    bug: str | None = None,
    status: str = "Draft",
    commits_block: str = "",
    hooks_block: str = "",
    timestamps_block: str = "",
) -> str:
    """Render one ProjectSpec Patch block in the canonical writer shape."""
    from sase.ace.patch.models import normalize_pr_origin
    from sase.ace.patch.review_field import format_review_url_line

    description_lines = _collapse_description_blank_runs(description)
    formatted_description = "\n".join(f"  {line}" for line in description_lines)
    parent_line = f"PARENT: {parent}\n" if parent else ""
    pr_line = format_review_url_line(pr_url) if pr_url else ""
    pr_origin_line = (
        f"PR_ORIGIN: {normalize_pr_origin(pr_origin)}\n"
        if pr_origin is not None
        else ""
    )
    bug_line = f"BUG: {bug}\n" if bug else ""

    return f"""

NAME: {name}
DESCRIPTION:
{formatted_description}
{parent_line}{pr_line}{pr_origin_line}{bug_line}STATUS: {status}
{commits_block}{hooks_block}{timestamps_block}"""


def _collapse_description_blank_runs(description: str) -> list[str]:
    lines = description.strip().split("\n")
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank:
            if not previous_blank:
                collapsed.append("")
            previous_blank = True
            continue
        collapsed.append(line)
        previous_blank = False
    return collapsed


__all__ = [
    "CANONICAL_PATCH_HEADING",
    "DEFAULT_STITCH_SECTION_HEADER",
    "format_patch_block",
    "LEGACY_PATCH_HEADING",
    "LEGACY_STITCH_SECTION_HEADER",
    "STITCH_SECTION_HEADERS",
    "is_patch_heading",
    "is_record_separator_line",
    "is_stitch_section_header",
    "stitch_section_header_for",
]
