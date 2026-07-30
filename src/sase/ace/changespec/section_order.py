"""Canonical ChangeSpec field and section ordering."""

from .review_field import REVIEW_URL_PREFIXES


CHANGESPEC_SECTION_ORDER: tuple[str, ...] = (
    "NAME:",
    "DESCRIPTION:",
    "PARENT:",
    *REVIEW_URL_PREFIXES,
    "BUG:",
    "STATUS:",
    "REFS:",
    "COMMITS:",
    "DELTAS:",
    "HOOKS:",
    "COMMENTS:",
    "MENTORS:",
    "TIMESTAMPS:",
)


__all__ = ["CHANGESPEC_SECTION_ORDER"]
