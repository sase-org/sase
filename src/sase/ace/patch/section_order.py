"""Canonical Patch field and section ordering."""

from .review_field import REVIEW_URL_PREFIXES
from .storage import DEFAULT_STITCH_SECTION_HEADER, LEGACY_STITCH_SECTION_HEADER


PATCH_SECTION_ORDER: tuple[str, ...] = (
    "NAME:",
    "DESCRIPTION:",
    "PARENT:",
    *REVIEW_URL_PREFIXES,
    "BUG:",
    "STATUS:",
    "REFS:",
    DEFAULT_STITCH_SECTION_HEADER,
    LEGACY_STITCH_SECTION_HEADER,
    "DELTAS:",
    "HOOKS:",
    "COMMENTS:",
    "MENTORS:",
    "TIMESTAMPS:",
)

CHANGESPEC_SECTION_ORDER: tuple[str, ...] = (
    "NAME:",
    "DESCRIPTION:",
    "PARENT:",
    *REVIEW_URL_PREFIXES,
    "BUG:",
    "STATUS:",
    "REFS:",
    LEGACY_STITCH_SECTION_HEADER,
    "DELTAS:",
    "HOOKS:",
    "COMMENTS:",
    "MENTORS:",
    "TIMESTAMPS:",
)

PROJECT_SPEC_SECTION_HEADERS: tuple[str, ...] = tuple(
    dict.fromkeys((*PATCH_SECTION_ORDER, *CHANGESPEC_SECTION_ORDER))
)

__all__ = [
    "CHANGESPEC_SECTION_ORDER",
    "PATCH_SECTION_ORDER",
    "PROJECT_SPEC_SECTION_HEADERS",
]
