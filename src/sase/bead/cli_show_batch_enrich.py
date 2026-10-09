"""Artifact-link enrichment for ``sase bead show`` batches."""

from __future__ import annotations

import logging
from dataclasses import replace

from sase.bead.cli_detail_links import assemble_bead_link_neighborhood
from sase.bead.cli_detail_resolution import IssueDetail

log = logging.getLogger(__name__)

#: What `assemble_bead_link_neighborhood` raises when the artifact-link store
#: cannot be read. Each caller decides whether to report it or degrade.
ARTIFACT_LINK_NEIGHBORHOOD_ERRORS = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
)


def artifact_link_neighborhood_detail(detail: IssueDetail) -> IssueDetail:
    """Return *detail* with its typed artifact-link neighborhood attached."""
    return replace(
        detail,
        artifact_links=assemble_bead_link_neighborhood(
            bead_id=detail.issue.id,
            bead_owned_rows=detail.bead_owned_artifact_links,
            fallback_issue=detail.issue,
        ),
    )


def enrich_with_artifact_link_neighborhood(detail: IssueDetail) -> IssueDetail:
    """Attach the link neighborhood, or leave *detail* unchanged on failure.

    `sase bead show` reports the failure and exits, which a host that is not a
    CLI entry point must never do — the pager resolves `bead:` links from
    inside a keypress handler. Degrading here costs that document its LINKS
    section rather than the whole document.
    """
    try:
        return artifact_link_neighborhood_detail(detail)
    except ARTIFACT_LINK_NEIGHBORHOOD_ERRORS:
        log.warning(
            "could not assemble the artifact-link neighborhood for %s",
            detail.issue.id,
            exc_info=True,
        )
        return detail


__all__ = [
    "ARTIFACT_LINK_NEIGHBORHOOD_ERRORS",
    "artifact_link_neighborhood_detail",
    "enrich_with_artifact_link_neighborhood",
]
