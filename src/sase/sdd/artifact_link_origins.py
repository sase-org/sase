"""Every artifact-link origin the host writes, and the subsets derived from it.

``ARTIFACT_LINK_HOST_ORIGINS`` is the single source of truth for the origin
strings sase stamps on artifact-link rows and events. Each one must parse as a
sase-core ``ArtifactLinkOriginWire`` variant: the contract test in
``tests/sdd/test_artifact_link_host_origins_contract.py`` round-trips every
entry through ``sase_core_rs.artifact_link_validate_row``, so an origin added
here without Rust support fails that test instead of failing every publication
pass with "unknown variant".

Callers branch on the derived subsets below, never on string literals, so a new
origin states its semantics once, in ``_ORIGIN_TRAITS``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _OriginTraits:
    """How the host treats rows and events carrying one origin."""

    name: str
    # Written from agent activity (a prompt or an audited read), so it lands
    # in a "Referenced By" table rather than the curated "Links" table.
    automatic: bool
    # Curated by a person, a migration, or a derivation rule; rendered in the
    # managed "Links" table.
    curated: bool
    # Drained from a commit-granular ``ReferencedByOutboxItem``: a repeated
    # drain of the same commit's entry converges its ``uses`` count instead of
    # accumulating it.
    commit_scoped: bool
    # A repeat observation counts another use. Matches sase-core's
    # ``ArtifactLinkOriginWire::increments_uses`` and becomes an
    # ``observation`` canonical event rather than an ``edge-put``.
    usage_bearing: bool
    # Machine-written events with this origin drain from the outbox without
    # per-run release evidence when a known machine producer wrote them.
    machine_trusted: bool


_ORIGIN_TRAITS: tuple[_OriginTraits, ...] = (
    _OriginTraits(
        "manual",
        automatic=False,
        curated=True,
        commit_scoped=False,
        usage_bearing=False,
        machine_trusted=False,
    ),
    _OriginTraits(
        "migrated",
        automatic=False,
        curated=True,
        commit_scoped=False,
        usage_bearing=False,
        machine_trusted=True,
    ),
    _OriginTraits(
        "prompt_ref",
        automatic=True,
        curated=False,
        commit_scoped=True,
        usage_bearing=True,
        machine_trusted=True,
    ),
    # A plan or research citation detected in prompt prose. It behaves like
    # ``prompt_ref`` everywhere but is never relabeled as one, so recorded
    # provenance survives.
    _OriginTraits(
        "prompt_prose",
        automatic=True,
        curated=False,
        commit_scoped=True,
        usage_bearing=True,
        machine_trusted=True,
    ),
    _OriginTraits(
        "read",
        automatic=True,
        curated=False,
        commit_scoped=False,
        usage_bearing=True,
        machine_trusted=False,
    ),
    _OriginTraits(
        "derived",
        automatic=False,
        curated=True,
        commit_scoped=False,
        usage_bearing=False,
        machine_trusted=True,
    ),
    _OriginTraits(
        "projected",
        automatic=False,
        curated=False,
        commit_scoped=False,
        usage_bearing=False,
        machine_trusted=False,
    ),
)

ARTIFACT_LINK_HOST_ORIGINS: tuple[str, ...] = tuple(
    traits.name for traits in _ORIGIN_TRAITS
)
ARTIFACT_LINK_AUTOMATIC_ORIGINS: frozenset[str] = frozenset(
    traits.name for traits in _ORIGIN_TRAITS if traits.automatic
)
ARTIFACT_LINK_CURATED_ORIGINS: frozenset[str] = frozenset(
    traits.name for traits in _ORIGIN_TRAITS if traits.curated
)
ARTIFACT_LINK_COMMIT_SCOPED_ORIGINS: frozenset[str] = frozenset(
    traits.name for traits in _ORIGIN_TRAITS if traits.commit_scoped
)
ARTIFACT_LINK_USAGE_BEARING_ORIGINS: frozenset[str] = frozenset(
    traits.name for traits in _ORIGIN_TRAITS if traits.usage_bearing
)
ARTIFACT_LINK_MACHINE_TRUSTED_ORIGINS: frozenset[str] = frozenset(
    traits.name for traits in _ORIGIN_TRAITS if traits.machine_trusted
)

__all__ = [
    "ARTIFACT_LINK_AUTOMATIC_ORIGINS",
    "ARTIFACT_LINK_COMMIT_SCOPED_ORIGINS",
    "ARTIFACT_LINK_CURATED_ORIGINS",
    "ARTIFACT_LINK_HOST_ORIGINS",
    "ARTIFACT_LINK_MACHINE_TRUSTED_ORIGINS",
    "ARTIFACT_LINK_USAGE_BEARING_ORIGINS",
]
