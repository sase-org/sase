"""Shared show-batch models for the ``cli_show_batch_*`` split modules.

This private module owns the data shapes and tiny helpers needed by more
than one ``cli_show_batch_*`` split module. Names are public so the split
modules can import them without a ``_``-prefixed cross-module import.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_show_router import RoutedShowStore
from sase.bead.model import Issue

if TYPE_CHECKING:
    from sase.bead.cross_project import BeadStoreOrigin


@dataclass(frozen=True)
class ShowFailure:
    """One requested bead ID that could not be resolved."""

    requested_id: str
    message: str


@dataclass(frozen=True)
class ShowEntry:
    """One resolved bead in argv order."""

    requested_id: str
    issue: Issue
    detail: IssueDetail | None
    origin: BeadStoreOrigin | None


@dataclass(frozen=True)
class ShowBatch:
    """Resolved ``sase bead show`` batch plus ordered failures."""

    entries: tuple[ShowEntry, ...]
    failures: tuple[ShowFailure, ...]
    multi_requested: bool


@dataclass(frozen=True)
class ShowRequest:
    """One requested ID, optionally pinned to an already-routed store."""

    requested_id: str
    store: RoutedShowStore | None = None


DetailEnricher = Callable[[IssueDetail], IssueDetail]
ReferenceContextFactory = Callable[[], ArtifactRefContext | None]
CreatorUrlResolver = Callable[[str], str | None]
PageUrlResolver = Callable[[str], str | None]
ShowRenderContextResolver = Callable[["BeadStoreOrigin | None"], "ShowRenderContext"]


@dataclass(frozen=True)
class ShowRenderContext:
    """Workspace-derived presentation context for one show entry origin."""

    relativize_design: bool
    plan_roots: tuple[Path, ...]
    design_cwd: Path | None
    reference_context_factory: ReferenceContextFactory
    creator_url_for: CreatorUrlResolver
    page_url_for: PageUrlResolver


def render_context_key(origin: BeadStoreOrigin | None) -> object:
    """Return the memoization key for one show entry origin."""
    if origin is None:
        return None
    return (origin.project_key, origin.primary_workspace)


__all__ = [
    "CreatorUrlResolver",
    "DetailEnricher",
    "PageUrlResolver",
    "ReferenceContextFactory",
    "ShowBatch",
    "ShowEntry",
    "ShowFailure",
    "ShowRenderContext",
    "ShowRenderContextResolver",
    "ShowRequest",
    "render_context_key",
]
