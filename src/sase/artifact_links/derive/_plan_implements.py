"""Derive `implements` rows from a plan's `bead:` frontmatter."""

from __future__ import annotations

from collections.abc import Collection

from sase.artifact_links.derive._model import DerivableDocument, DerivedLinkCandidate
from sase.sdd.plan_tiers import parse_plan_frontmatter

_PLAN_KIND = "plan"


def derive_plan_implements_bead(
    document: DerivableDocument,
    *,
    known_bead_ids: Collection[str],
) -> tuple[DerivedLinkCandidate, ...]:
    """Emit one `implements` row when *document*'s frontmatter names a live bead.

    A plan implements a bead's requirements, so the row is directed
    `plan:<relpath> implements bead:<id>`. Skips silently rather than writing
    a dangling row: a non-plan ref, unreadable or invalid frontmatter, a
    missing or blank `bead` field, and a bead id absent from
    *known_bead_ids* all yield no candidate.
    """

    kind, _, _ = document.ref.partition(":")
    if kind != _PLAN_KIND:
        return ()
    try:
        content = document.path.read_text(encoding="utf-8")
    except OSError:
        return ()
    frontmatter, error = parse_plan_frontmatter(content)
    if error is not None:
        return ()
    raw_bead_id = frontmatter.get("bead")
    if not isinstance(raw_bead_id, str):
        return ()
    bead_id = raw_bead_id.strip()
    if not bead_id or bead_id not in known_bead_ids:
        return ()
    return (
        DerivedLinkCandidate(
            source_ref=document.ref,
            relation="implements",
            target_ref=f"bead:{bead_id}",
            description="derived from the plan's `bead:` frontmatter field",
        ),
    )
