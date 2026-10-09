"""Compatibility facade for ``sase bead show`` batch handling.

The batch models, resolution, render context, and rendering live in focused
modules; this module keeps the historical ``sase.bead.cli_show_batch``
import surface intact. Patch the module that defines a symbol
(``cli_show_batch_enrich``, ``cli_show_batch_resolve``,
``cli_show_batch_context``, ``cli_show_batch_render``), not this facade —
except ``resolve_show_batch``, which pager callers re-import from here at
call time.
"""

from __future__ import annotations

from sase.bead._cli_show_batch_shared import (
    CreatorUrlResolver as CreatorUrlResolver,
    DetailEnricher as DetailEnricher,
    PageUrlResolver as PageUrlResolver,
    ReferenceContextFactory as ReferenceContextFactory,
)
from sase.bead.cli_show_batch_context import default_show_render_context_resolver
from sase.bead.cli_show_batch_enrich import (
    ARTIFACT_LINK_NEIGHBORHOOD_ERRORS,
    artifact_link_neighborhood_detail,
    enrich_with_artifact_link_neighborhood,
)
from sase.bead.cli_show_batch_render import (
    build_show_batch_document,
    render_show_batch,
    render_show_document,
)
from sase.bead.cli_show_batch_resolve import resolve_show_batch

__all__ = [
    "ARTIFACT_LINK_NEIGHBORHOOD_ERRORS",
    "artifact_link_neighborhood_detail",
    "build_show_batch_document",
    "default_show_render_context_resolver",
    "enrich_with_artifact_link_neighborhood",
    "render_show_batch",
    "render_show_document",
    "resolve_show_batch",
]
