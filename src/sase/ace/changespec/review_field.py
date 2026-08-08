"""Legacy review-field names backed by :mod:`sase.ace.patch.review_field`."""

from sase.ace.patch.review_field import (
    LEGACY_REVIEW_URL_LABEL,
    PRIMARY_REVIEW_URL_LABEL,
    REVIEW_URL_LABELS,
    REVIEW_URL_PREFIXES,
    REVIEW_URL_PREFIXES_WITH_SPACE,
    format_review_url_line,
    is_review_url_line,
    parse_review_url_line,
)

__all__ = [
    "LEGACY_REVIEW_URL_LABEL",
    "PRIMARY_REVIEW_URL_LABEL",
    "REVIEW_URL_LABELS",
    "REVIEW_URL_PREFIXES",
    "REVIEW_URL_PREFIXES_WITH_SPACE",
    "format_review_url_line",
    "is_review_url_line",
    "parse_review_url_line",
]
