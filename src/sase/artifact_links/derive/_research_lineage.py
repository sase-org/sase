"""Derive `derives-from` rows from research-swarm __a/__b sibling files."""

from __future__ import annotations

from sase.artifact_links.derive._model import DerivableDocument, DerivedLinkCandidate

_RESEARCH_KIND = "research"
_SWARM_SUFFIXES = ("__a", "__b")


def derive_research_swarm_lineage(
    document: DerivableDocument,
) -> tuple[DerivedLinkCandidate, ...]:
    """Emit `derives-from` rows for a research lead's on-disk `__a`/`__b` siblings.

    Only a lead document -- one whose ref does not itself carry a `__a`/`__b`
    suffix -- can derive; a swarm source is never itself a lead. Derives from
    the on-disk shape rather than the rename commit.
    """

    kind, _, relpath = document.ref.partition(":")
    if kind != _RESEARCH_KIND or not relpath:
        return ()
    stem = document.path.stem
    if stem.endswith(_SWARM_SUFFIXES):
        return ()

    candidates: list[DerivedLinkCandidate] = []
    for suffix in _SWARM_SUFFIXES:
        sibling_path = document.path.with_name(f"{stem}{suffix}{document.path.suffix}")
        if not sibling_path.is_file():
            continue
        sibling_ref = f"{_RESEARCH_KIND}:{_sibling_relpath(relpath, sibling_path.name)}"
        candidates.append(
            DerivedLinkCandidate(
                source_ref=document.ref,
                relation="derives-from",
                target_ref=sibling_ref,
                description=(
                    "research-swarm lineage: "
                    f"{sibling_path.name} is a consolidation source on disk"
                ),
            )
        )
    return tuple(candidates)


def _sibling_relpath(lead_relpath: str, sibling_name: str) -> str:
    parent, separator, _ = lead_relpath.rpartition("/")
    return f"{parent}{separator}{sibling_name}"
