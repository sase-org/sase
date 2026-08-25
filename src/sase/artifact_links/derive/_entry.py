"""Single fan-out entry point over every artifact-link derivation rule."""

from __future__ import annotations

from collections.abc import Collection, Iterable

from sase.artifact_links.derive._model import DerivableDocument, DerivedLinkCandidate
from sase.artifact_links.derive._plan_implements import derive_plan_implements_bead
from sase.artifact_links.derive._research_lineage import derive_research_swarm_lineage


def derive_candidate_links(
    documents: Iterable[DerivableDocument],
    *,
    known_bead_ids: Collection[str],
) -> tuple[DerivedLinkCandidate, ...]:
    """Run every derivation rule over *documents* and return candidate rows.

    Writes nothing itself: the caller owns persistence and its own flag
    check (``artifact_link_derivation_enabled``). A document whose ref kind
    no rule recognizes contributes no candidates.
    """

    candidates: list[DerivedLinkCandidate] = []
    for document in documents:
        candidates.extend(derive_research_swarm_lineage(document))
        candidates.extend(
            derive_plan_implements_bead(document, known_bead_ids=known_bead_ids)
        )
    return tuple(candidates)
