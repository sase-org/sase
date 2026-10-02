"""The link-traversing SASE pager: a document reading surface with painted
jump-hint keys over every scanned typed ref, URL, path, and bare token.

See ``plan:202608/link_traversing_pager.md`` for the full design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS = {
    "AttachedTarget": ("sase.pager.document", "AttachedTarget"),
    "AttachedTargetHandler": ("sase.pager.app", "AttachedTargetHandler"),
    "BoundedLinkScan": ("sase.pager.link_scan", "BoundedLinkScan"),
    "LabelWindowScope": ("sase.pager._labels", "LabelWindowScope"),
    "LinkAnchor": ("sase.pager.link_context", "LinkAnchor"),
    "LinkResolutionContext": ("sase.pager.link_context", "LinkResolutionContext"),
    "LinkSpan": ("sase.pager.link_scan", "LinkSpan"),
    "LinkSpanKind": ("sase.pager.link_scan", "LinkSpanKind"),
    "PAGER_LABEL_ALPHABET": ("sase.pager._labels", "PAGER_LABEL_ALPHABET"),
    "PAGER_LABEL_TWO_KEY_CAPACITY": (
        "sase.pager._labels",
        "PAGER_LABEL_TWO_KEY_CAPACITY",
    ),
    "PAGER_TRAIL_LIMIT": ("sase.pager.trail", "PAGER_TRAIL_LIMIT"),
    "PagerDocument": ("sase.pager.document", "PagerDocument"),
    "PagerExit": ("sase.pager.app", "PagerExit"),
    "PagerLabel": ("sase.pager._labels", "PagerLabel"),
    "PagerLabelLayer": ("sase.pager._labels", "PagerLabelLayer"),
    "PagerOrigin": ("sase.pager.link_scan", "PagerOrigin"),
    "PagerScreen": ("sase.pager.screen", "PagerScreen"),
    "PagerSearchState": ("sase.pager.trail", "PagerSearchState"),
    "PagerSection": ("sase.pager.document", "PagerSection"),
    "PagerTargetSource": ("sase.pager.document", "PagerTargetSource"),
    "PagerTargetSpan": ("sase.pager.document", "PagerTargetSpan"),
    "PagerTrailEntry": ("sase.pager.trail", "PagerTrailEntry"),
    "SasePager": ("sase.pager.app", "SasePager"),
    "append_bounded_trail": ("sase.pager.trail", "append_bounded_trail"),
    "build_label_layer": ("sase.pager._labels", "build_label_layer"),
    "document_from_paths": ("sase.pager.adapters", "document_from_paths"),
    "path_section": ("sase.pager.adapters", "path_section"),
    "path_sections": ("sase.pager.adapters", "path_sections"),
    "render_section_with_labels": (
        "sase.pager._labels",
        "render_section_with_labels",
    ),
    "scan_bounded_links": ("sase.pager.link_scan", "scan_bounded_links"),
    "scan_links": ("sase.pager.link_scan", "scan_links"),
    "section_origin": ("sase.pager.document", "section_origin"),
    "section_target_spans": ("sase.pager.document", "section_target_spans"),
    "target_action_destination": (
        "sase.pager.document",
        "target_action_destination",
    ),
    "target_resolution_cache_identity": (
        "sase.pager.document",
        "target_resolution_cache_identity",
    ),
    "target_resolution_ref": ("sase.pager.document", "target_resolution_ref"),
}

__all__ = [
    "BoundedLinkScan",
    "AttachedTarget",
    "AttachedTargetHandler",
    "LinkAnchor",
    "LinkResolutionContext",
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
    "section_origin",
    "section_target_spans",
    "target_action_destination",
    "target_resolution_cache_identity",
    "target_resolution_ref",
]

if TYPE_CHECKING:
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
    from sase.pager.app import AttachedTargetHandler, PagerExit, SasePager
    from sase.pager.document import (
        AttachedTarget,
        PagerDocument,
        PagerSection,
        PagerTargetSpan,
        PagerTargetSource,
        section_origin,
        section_target_spans,
        target_action_destination,
        target_resolution_cache_identity,
        target_resolution_ref,
    )
    from sase.pager.link_context import LinkAnchor, LinkResolutionContext
    from sase.pager.link_scan import (
        BoundedLinkScan,
        LinkSpan,
        LinkSpanKind,
        PagerOrigin,
        scan_bounded_links,
        scan_links,
    )
    from sase.pager.screen import PagerScreen
    from sase.pager.trail import (
        PAGER_TRAIL_LIMIT,
        PagerSearchState,
        PagerTrailEntry,
        append_bounded_trail,
    )


def __getattr__(name: str) -> object:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__
