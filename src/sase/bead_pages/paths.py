"""The single authority for where a bead's generated page lives.

Addressing is lexical and derivable offline: a bead id's lineage root is the
segment before its first ``.``, the root bead takes ``README.md`` so GitHub
renders it when browsing the directory, and every descendant takes
``<full-id>.md``. Nothing here consults the bead store, which is what lets a
``SASE_BEAD`` commit tag link to a page the same commit has not published yet.
"""

from __future__ import annotations

import re

BEAD_PAGES_DIRNAME = "pages"
"""Directory inside the beads sidecar that holds generated bead pages.

This deliberately is not ``beads``. ``resolve_beads_dir`` locates a bead store
by collecting ``root/sdd/beads``, ``root/beads``, and ``root`` itself, then
bailing out when those candidates disagree, so a ``beads/`` directory at the
sidecar root would make every bead store resolution in that repository
ambiguous.
"""

BEAD_PAGE_SUFFIX = ".md"
"""Extension shared by every rendered bead page."""

BEAD_ROOT_PAGE_FILENAME = f"README{BEAD_PAGE_SUFFIX}"
"""Filename a lineage root takes so GitHub renders it for the directory."""

_INVALID_SEGMENT_RE = re.compile(r"^\s*$|[\s/\\]")


def bead_lineage_root(bead_id: str) -> str:
    """Return the lexical lineage root of *bead_id*.

    The root is the segment before the first ``.``, so ``sase-ag.1``,
    ``sase-ag.land``, and ``sase-26.1.1`` belong to ``sase-ag``, ``sase-ag``,
    and ``sase-26`` respectively.
    """

    return _normalized_bead_id(bead_id).split(".", 1)[0]


def bead_page_root(bead_id: str) -> str:
    """Return the repo-relative directory holding *bead_id*'s lineage pages."""

    return f"{BEAD_PAGES_DIRNAME}/{bead_lineage_root(bead_id)}"


def bead_page_path(bead_id: str) -> str:
    """Return *bead_id*'s page as a beads-repo-relative posix path."""

    normalized = _normalized_bead_id(bead_id)
    root = bead_lineage_root(normalized)
    filename = (
        BEAD_ROOT_PAGE_FILENAME
        if normalized == root
        else f"{normalized}{BEAD_PAGE_SUFFIX}"
    )
    return f"{bead_page_root(normalized)}/{filename}"


def _normalized_bead_id(bead_id: str) -> str:
    """Return *bead_id* stripped, rejecting anything that cannot be a path."""

    normalized = (bead_id or "").strip()
    if not normalized:
        raise ValueError("bead id is empty")
    segments = normalized.split(".")
    for segment in segments:
        if not segment or _INVALID_SEGMENT_RE.search(segment):
            raise ValueError(f"bead id is not a valid page address: {bead_id!r}")
    return normalized


__all__ = [
    "BEAD_PAGES_DIRNAME",
    "BEAD_PAGE_SUFFIX",
    "BEAD_ROOT_PAGE_FILENAME",
    "bead_lineage_root",
    "bead_page_path",
    "bead_page_root",
]
