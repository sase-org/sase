"""Per-operation publication state for immutable artifact-link events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.sdd._artifact_link_event_canonical import ArtifactLinkEventObject
from sase.sdd._artifact_link_event_ownership import (
    document_kinds_for_store,
    event_owner_requirements,
    resolved_document_roots_for_store,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore


@dataclass(slots=True)
class OperationPublicationState:
    """Mutable receipt state for one canonical event operation."""

    item: ArtifactLinkEventObject
    requirements: dict[str, Any]
    resolved_roots: dict[str, Path]
    forced_roots: tuple[Path, ...]
    bead_owner: bool
    durable_roots: set[Path]
    local_receipt: bool = False

    @property
    def operation_id(self) -> str:
        return str(self.item.event["operation_id"])

    @property
    def event_key(self) -> tuple[str, str]:
        return self.operation_id, self.item.digest


def operation_states(
    store: ArtifactLinkStore,
    objects: Sequence[ArtifactLinkEventObject],
    *,
    extra_roots: Sequence[Path] = (),
) -> dict[str, OperationPublicationState]:
    """Return per-digest publication state for *objects*."""

    document_kinds = document_kinds_for_store(store)
    forced = tuple(
        dict.fromkeys(
            Path(root).expanduser().resolve(strict=False) for root in extra_roots
        )
    )
    states: dict[str, OperationPublicationState] = {}
    for item in objects:
        requirements = event_owner_requirements(item.event, document_kinds)
        bead_refs = requirements.get("bead_refs")
        states[item.digest] = OperationPublicationState(
            item=item,
            requirements=requirements,
            resolved_roots=resolved_document_roots_for_store(store, requirements),
            forced_roots=forced,
            bead_owner=bool(bead_refs),
            durable_roots=set(),
        )
    return states


def required_roots(state: OperationPublicationState) -> tuple[Path, ...]:
    """Return resolved and forced roots that must durably store *state*."""

    return tuple(dict.fromkeys((*state.resolved_roots.values(), *state.forced_roots)))


__all__ = [
    "OperationPublicationState",
    "operation_states",
    "required_roots",
]
