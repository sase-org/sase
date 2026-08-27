"""The link-traversing SASE pager: a document reading surface with painted
jump-hint keys over every scanned typed ref, URL, path, and bare token.

See ``plan:202608/link_traversing_pager.md`` for the full design.
"""

from __future__ import annotations

from sase.pager.app import AttachedTargetHandler, PagerExit, SasePager
from sase.pager.screen import PagerScreen
from sase.pager._labels import (
    LabelWindowScope,
    PAGER_LABEL_ALPHABET,
    PAGER_LABEL_TWO_KEY_CAPACITY,
    PagerLabel,
    PagerLabelLayer,
    build_label_layer,
    render_section_with_labels,
)
from sase.pager.adapters import document_from_paths, path_section, path_sections
from sase.pager.document import (
    AttachedTarget,
    PagerDocument,
    PagerSection,
    PagerTargetSpan,
    PagerTargetSource,
    section_target_spans,
)
from sase.pager.link_scan import (
    BoundedLinkScan,
    LinkSpan,
    LinkSpanKind,
    PagerOrigin,
    scan_bounded_links,
    scan_links,
)
from sase.pager.trail import (
    PAGER_TRAIL_LIMIT,
    PagerSearchState,
    PagerTrailEntry,
    append_bounded_trail,
)

__all__ = [
    "BoundedLinkScan",
    "AttachedTarget",
    "AttachedTargetHandler",
    "LinkSpan",
    "LinkSpanKind",
    "LabelWindowScope",
    "PAGER_LABEL_ALPHABET",
    "PAGER_LABEL_TWO_KEY_CAPACITY",
    "PAGER_TRAIL_LIMIT",
    "PagerDocument",
    "PagerExit",
    "PagerLabel",
    "PagerLabelLayer",
    "PagerOrigin",
    "PagerSearchState",
    "PagerSection",
    "PagerScreen",
    "PagerTargetSpan",
    "PagerTargetSource",
    "PagerTrailEntry",
    "SasePager",
    "append_bounded_trail",
    "document_from_paths",
    "path_section",
    "path_sections",
    "build_label_layer",
    "render_section_with_labels",
    "scan_bounded_links",
    "scan_links",
    "section_target_spans",
]
