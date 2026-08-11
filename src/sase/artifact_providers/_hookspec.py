"""Pluggy hook specifications for artifact provider plugins."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pluggy

hookspec = pluggy.HookspecMarker("sase_artifact")
hookimpl = pluggy.HookimplMarker("sase_artifact")


class ArtifactProviderHookSpec:
    """Hook specifications for declarative artifact providers."""

    @hookspec
    def artifact_ref_provider_specs(
        self,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return document artifact-reference provider specs."""
        ...

    @hookspec
    def artifact_file_hook_provider_specs(
        self,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return file-hook provider templates."""
        ...


__all__ = [
    "ArtifactProviderHookSpec",
    "hookimpl",
    "hookspec",
]
