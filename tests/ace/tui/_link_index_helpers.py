"""Shared helpers for the ``test_link_index*`` test modules.

Public helpers used by more than one ``test_link_index_*`` module live here
under public names so no new module imports a ``_``-prefixed name from
another new module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot

__all__ = ["snapshot"]


def snapshot(rows: tuple[Mapping[str, Any], ...]) -> ArtifactLinksSnapshot:
    return ArtifactLinksSnapshot(rows=rows, source_key=("test",))
