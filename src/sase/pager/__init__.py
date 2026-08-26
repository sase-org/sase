"""The link-traversing SASE pager: a document reading surface with painted
jump-hint keys over every scanned typed ref, URL, path, and bare token.

See ``plan:202608/link_traversing_pager.md`` for the full design.
"""

from __future__ import annotations

from sase.pager.flag import link_pager_enabled
from sase.pager.link_scan import (
    BoundedLinkScan,
    LinkSpan,
    LinkSpanKind,
    PagerOrigin,
    scan_bounded_links,
    scan_links,
)

__all__ = [
    "BoundedLinkScan",
    "LinkSpan",
    "LinkSpanKind",
    "PagerOrigin",
    "link_pager_enabled",
    "scan_bounded_links",
    "scan_links",
]
