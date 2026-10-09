"""Bead-ID prefix discovery for pager bare-token recognition.

Textual-free. The cross-project import stays lazy inside the function so the
pager cold path does not pay for the project registry on import.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sase.pager.link_scan import normalize_bead_id_prefixes

log = logging.getLogger(__name__)


def _bead_id_prefix_of(bead_id: str) -> str | None:
    """Return the bead-ID prefix for *bead_id*, or ``None``.

    Takes the top-level segment before the first ``.`` and splits off the
    trailing ``-<counter>`` with ``rpartition("-")``. Returns ``None`` when
    there is no separator or the prefix is empty. Pure string work; no
    bead-package import.
    """
    top_level = bead_id.split(".", maxsplit=1)[0]
    prefix, separator, _counter = top_level.rpartition("-")
    if not separator or not prefix:
        return None
    return prefix


def pager_bead_id_prefixes(
    bead_ids: Iterable[str] = (),
    *,
    include_enabled_projects: bool = True,
) -> tuple[str, ...]:
    """Return the union of ID-derived and enabled-project bead-ID prefixes.

    The enabled-project part is best-effort: any lookup failure is logged at
    debug and degrades to the ID-derived prefixes, because a document build
    must never fail over hints.
    """
    prefixes: set[str] = set()
    for bead_id in bead_ids:
        prefix = _bead_id_prefix_of(bead_id)
        if prefix is not None:
            prefixes.add(prefix)
    if include_enabled_projects:
        try:
            from sase.bead.cross_project import enabled_project_ref_prefixes

            prefixes.update(enabled_project_ref_prefixes())
        except Exception:  # noqa: BLE001 - hints must never break a build
            log.debug("pager bead prefix lookup failed", exc_info=True)
    return normalize_bead_id_prefixes(prefixes)


__all__ = ["pager_bead_id_prefixes"]
