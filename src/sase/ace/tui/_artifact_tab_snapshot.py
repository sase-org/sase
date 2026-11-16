"""Immutable Artifacts descriptor snapshot and pure lookup operations.

The process discovery cache in :mod:`sase.ace.tui.artifact_tabs` is not a
presentation boundary. UI consumers read an app-owned
:class:`ArtifactsDescriptorSnapshot` so a later cache refresh cannot change
bindings, the tab strip, help, catalogs, or navigation independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import count
from typing import Any

from ._artifact_tab_model import (
    ARTIFACTS_ITEM_NOUNS,
    ARTIFACTS_LABELS,
    DEFAULT_ARTIFACTS_SUBTAB,
    LEGACY_ARTIFACTS_SUBTABS,
    ArtifactsPaneContract,
    ArtifactsPaneKey,
    ArtifactsSubTab,
    ArtifactsTabDescriptor,
    FilesSubTab,
)


class ArtifactsDiscoveryStatus(StrEnum):
    """How the descriptors in a snapshot were produced."""

    BOOTSTRAP = "bootstrap"
    COMPLETED = "completed"
    FAILED = "failed"


_GENERATION_SEQ = count(1)


def _next_artifacts_snapshot_generation() -> int:
    """Return a fresh generation identity for a newly published snapshot."""

    return next(_GENERATION_SEQ)


def _pane_fallback(pane_id: str) -> str:
    return pane_id.rsplit(":", 1)[-1].replace("_", " ").replace("-", " ").title()


@dataclass(frozen=True, slots=True)
class ArtifactsDescriptorSnapshot:
    """One coherent Artifacts generation for TUI presentation consumers."""

    descriptors: tuple[ArtifactsTabDescriptor, ...]
    generation: int
    status: ArtifactsDiscoveryStatus
    source_token: tuple[object, ...] | None
    source_epoch: int

    @property
    def ordered_ids(self) -> tuple[ArtifactsSubTab, ...]:
        return tuple(descriptor.id for descriptor in self.descriptors)

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(
            descriptor.id for descriptor in self.descriptors if descriptor.is_provider
        )

    @property
    def is_pending(self) -> bool:
        return self.status is ArtifactsDiscoveryStatus.BOOTSTRAP

    @property
    def is_completed_zero_providers(self) -> bool:
        return (
            self.status is ArtifactsDiscoveryStatus.COMPLETED and not self.provider_ids
        )

    @property
    def is_failed(self) -> bool:
        return self.status is ArtifactsDiscoveryStatus.FAILED

    def lookup(self, pane_id: str) -> ArtifactsTabDescriptor | None:
        """Return the descriptor whose id matches *pane_id* exactly."""

        return next(
            (descriptor for descriptor in self.descriptors if descriptor.id == pane_id),
            None,
        )

    def lookup_digit(self, digit: str | int) -> ArtifactsTabDescriptor | None:
        """Return the descriptor carrying *digit* as its shortcut."""

        key = str(digit)
        return next(
            (
                descriptor
                for descriptor in self.descriptors
                if descriptor.digit_shortcut == key
            ),
            None,
        )

    def canonicalize(self, pane_id: str) -> str:
        return LEGACY_ARTIFACTS_SUBTABS.get(pane_id, pane_id)

    def normalize(self, value: str) -> ArtifactsSubTab:
        """Map a persisted or legacy identifier onto this generation."""

        canonical = self.canonicalize(value)
        if self.lookup(canonical) is not None:
            return canonical
        return DEFAULT_ARTIFACTS_SUBTAB

    def pane_key(
        self,
        subtab: ArtifactsSubTab,
        files_subtab: FilesSubTab | None = None,
    ) -> ArtifactsPaneKey:
        """Return the visible Artifacts pane id inside this generation."""

        if subtab == "files" and files_subtab:
            legacy = LEGACY_ARTIFACTS_SUBTABS.get(files_subtab)
            if legacy is not None:
                return self.normalize(legacy)
        return self.normalize(subtab)

    def descriptor_for_subtab(self, subtab: str) -> ArtifactsTabDescriptor | None:
        return self.lookup(self.normalize(subtab))

    def contract(self, pane_id: str) -> ArtifactsPaneContract | None:
        descriptor = self.lookup(self.canonicalize(pane_id))
        return None if descriptor is None else descriptor.contract

    def label(self, pane_id: str) -> str:
        canonical = self.canonicalize(pane_id)
        descriptor = self.lookup(canonical)
        if descriptor is not None and descriptor.contract is not None:
            return descriptor.contract.label
        return ARTIFACTS_LABELS.get(canonical, _pane_fallback(canonical))

    def item_noun(self, pane_id: str) -> str:
        canonical = self.canonicalize(pane_id)
        descriptor = self.lookup(canonical)
        if descriptor is not None and descriptor.contract is not None:
            return descriptor.contract.item_noun
        return ARTIFACTS_ITEM_NOUNS.get(canonical, _pane_fallback(canonical))

    def is_unconfigured_ref_pane(self, pane_id: str) -> bool:
        return pane_id.startswith("ref:") and self.lookup(pane_id) is None

    def is_document_pane(self, pane_id: str) -> bool:
        contract = self.contract(pane_id)
        if contract is not None:
            return contract.is_document_provider()
        return pane_id in {"ref:plan", "plans"}


def bootstrap_artifacts_snapshot(
    *,
    generation: int = 0,
) -> ArtifactsDescriptorSnapshot:
    """Return fixed panes only: no project walk, token read, or cache write."""

    from ._artifact_tab_descriptors import build_artifacts_strip

    return ArtifactsDescriptorSnapshot(
        descriptors=build_artifacts_strip(()),
        generation=generation,
        status=ArtifactsDiscoveryStatus.BOOTSTRAP,
        source_token=None,
        source_epoch=0,
    )


def snapshot_from_descriptors(
    descriptors: tuple[ArtifactsTabDescriptor, ...],
    *,
    status: ArtifactsDiscoveryStatus = ArtifactsDiscoveryStatus.COMPLETED,
    source_token: tuple[object, ...] | None = None,
    source_epoch: int = 0,
    generation: int | None = None,
) -> ArtifactsDescriptorSnapshot:
    """Wrap an already-built descriptor tuple as a presentation snapshot."""

    return ArtifactsDescriptorSnapshot(
        descriptors=descriptors,
        generation=(
            _next_artifacts_snapshot_generation() if generation is None else generation
        ),
        status=status,
        source_token=source_token,
        source_epoch=source_epoch,
    )


def discover_artifacts_snapshot() -> ArtifactsDescriptorSnapshot:
    """Run synchronous discovery and wrap the result as a snapshot.

    Standalone CLI, diagnostics, and this phase's app bootstrap use this
    factory. It may populate the process discovery cache; UI reads still go
    through the returned object, not later cache refreshes.
    """

    from ._artifact_tab_discovery import provider_source_token
    from .artifact_tabs import (
        artifacts_tab_cache_epoch,
        resolve_artifacts_subtabs,
    )

    token = provider_source_token()
    epoch = artifacts_tab_cache_epoch()
    descriptors = resolve_artifacts_subtabs()
    status = (
        ArtifactsDiscoveryStatus.FAILED
        if token is None
        else ArtifactsDiscoveryStatus.COMPLETED
    )
    return snapshot_from_descriptors(
        descriptors,
        status=status,
        source_token=token,
        source_epoch=epoch,
    )


def artifacts_snapshot_of(app: Any) -> ArtifactsDescriptorSnapshot | None:
    """Return the app-owned snapshot, or ``None`` when the host has none."""

    snapshot = getattr(app, "artifacts_descriptor_snapshot", None)
    return snapshot if isinstance(snapshot, ArtifactsDescriptorSnapshot) else None


def artifacts_snapshot_from_widget(widget: Any) -> ArtifactsDescriptorSnapshot | None:
    """Return the host snapshot, or ``None`` before the widget is attached."""

    try:
        app = widget.app
    except Exception:  # noqa: BLE001 - unmounted widgets have no active app
        return None
    return artifacts_snapshot_of(app)
