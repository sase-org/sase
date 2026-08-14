"""Disabled region protection for xprompt processing.

Provides utilities to extract regions enclosed by
``%xprompts_enabled:false`` / ``%xprompts_enabled:true`` marker pairs
from text before xprompt expansion and restore them afterward,
preventing content inside disabled regions from being processed.
"""

import re

_DISABLED_REGION_RE = re.compile(
    r"^[ \t]*%xprompts_enabled:false[ \t]*\n([\s\S]*?)(?:^[ \t]*|[ \t]+)%xprompts_enabled:true[ \t]*\n?",
    re.MULTILINE,
)
_DISABLED_REGION_START_RE = re.compile(r"[ \t]*%xprompts_enabled:false")
_MARKER_TEXT_RE = re.compile(r"%(xprompts_enabled:(?:false|true))")
_PLACEHOLDER_PREFIX = "\x00XPD_"
_PLACEHOLDER_SUFFIX = "\x00"


def ensure_disabled_region_at_line_start(content: str, is_at_line_start: bool) -> str:
    """Keep a leading disabled-region marker on a line boundary.

    Prompt-part references can appear after other content on the same line.
    When their rendered content begins with ``%xprompts_enabled:false``, the
    marker needs its own line so downstream disabled-region processing can
    recognize it.
    """
    if content and not is_at_line_start and _DISABLED_REGION_START_RE.match(content):
        return "\n" + content
    return content


def _escape_disabled_region_markers(text: str) -> str:
    """Neutralize marker-shaped text so it cannot open or close a region."""
    return _MARKER_TEXT_RE.sub(r"% \1", text)


def wrap_disabled_region(text: str) -> str:
    """Return *text* enclosed in a disabled region, marker-escaped first."""
    escaped = _escape_disabled_region_markers(text)
    return f"%xprompts_enabled:false\n{escaped}\n%xprompts_enabled:true"


def protect_disabled_regions(text: str, regions: list[str]) -> str:
    """Replace disabled regions with null-byte placeholders.

    Each extracted region (including its markers) is appended to
    ``regions``, using the list length as the starting index for
    placeholder numbering.

    Args:
        text: The text to scan for disabled regions.
        regions: Mutable list that accumulates extracted region content.

    Returns:
        The text with disabled regions replaced by placeholders.
    """

    def _replacer(m: re.Match[str]) -> str:
        idx = len(regions)
        regions.append(m.group(0))
        return f"{_PLACEHOLDER_PREFIX}{idx}{_PLACEHOLDER_SUFFIX}"

    return _DISABLED_REGION_RE.sub(_replacer, text)


def disabled_region_ranges(text: str) -> list[tuple[int, int]]:
    """Return (start, end) ranges for all disabled regions in *text*."""
    return [(m.start(), m.end()) for m in _DISABLED_REGION_RE.finditer(text)]


def strip_disabled_regions(text: str) -> str:
    """Remove whole disabled regions, including markers and enclosed content."""
    return _DISABLED_REGION_RE.sub("", text)


def unprotect_disabled_regions(text: str, regions: list[str]) -> str:
    """Restore all disabled region placeholders with original content.

    The markers are preserved in the restored text so downstream
    pipeline stages can still see (and eventually strip) them.

    Args:
        text: Text containing placeholders.
        regions: The list of extracted regions (populated by
            :func:`protect_disabled_regions`).

    Returns:
        The text with placeholders replaced by original disabled regions.
    """
    for i, region in enumerate(regions):
        text = text.replace(f"{_PLACEHOLDER_PREFIX}{i}{_PLACEHOLDER_SUFFIX}", region)
    return text


def strip_disabled_region_markers(text: str) -> str:
    """Remove all ``%xprompts_enabled:false/true`` marker lines.

    This should be called as a final cleanup step after all pipeline
    stages have finished processing.

    Args:
        text: The text to strip markers from.

    Returns:
        The text with all marker lines removed.
    """
    return re.sub(
        r"^[ \t]*%xprompts_enabled:(?:false|true)[ \t]*\n?|[ \t]+%xprompts_enabled:(?:false|true)[ \t]*",
        "",
        text,
        flags=re.MULTILINE,
    )
