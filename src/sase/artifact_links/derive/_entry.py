"""Single fan-out entry point over every artifact-link derivation rule."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from pathlib import Path

from sase.artifact_links.derive._agent_cites_plan import derive_agent_cites_plan
from sase.artifact_links.derive._model import DerivableDocument, DerivedLinkCandidate
from sase.artifact_links.derive._plan_implements import derive_plan_implements_bead
from sase.artifact_links.derive._research_lineage import derive_research_swarm_lineage


def derive_candidate_links(
    documents: Iterable[DerivableDocument],
    *,
    known_bead_ids: Collection[str],
    agents_sidecar_root: Path | None = None,
    is_agent_published: Callable[[str], bool] | None = None,
) -> tuple[DerivedLinkCandidate, ...]:
    """Run every derivation rule over *documents* and return candidate rows.

    Writes nothing itself: the caller owns persistence and its own flag
    check (``artifact_link_derivation_enabled``). A document whose ref kind
    no rule recognizes contributes no candidates. *agents_sidecar_root* and
    *is_agent_published* feed only ``derive_agent_cites_plan``; omitting
    either -- there being no agents sidecar clone here, or no publication
    check supplied -- makes that one rule a no-op rather than the whole
    entry point.
    """

    published_check = is_agent_published or _no_agent_published
    candidates: list[DerivedLinkCandidate] = []
    for document in documents:
        candidates.extend(derive_research_swarm_lineage(document))
        candidates.extend(
            derive_plan_implements_bead(document, known_bead_ids=known_bead_ids)
        )
        candidates.extend(
            derive_agent_cites_plan(
                document,
                agents_sidecar_root=agents_sidecar_root,
                is_agent_published=published_check,
            )
        )
    return tuple(candidates)


def _no_agent_published(agent_name: str) -> bool:  # noqa: ARG001 - default stub
    return False
