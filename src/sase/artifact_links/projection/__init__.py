"""Pure rules that recompute `origin: projected` rows from owned facts.

Mirrors :mod:`sase.artifact_links.derive`: every rule is a pure function
over already-loaded inputs, writes nothing itself, and the caller owns
persistence. Unlike `derive`, a projected row is never carried forward
between rebuilds -- it is recomputed every time, so a rule that stops
matching lets its row disappear rather than orphaning it.
"""

from __future__ import annotations

from sase.artifact_links.projection._entry import project_link_rows
from sase.artifact_links.projection._inputs import build_projection_inputs
from sase.artifact_links.projection._model import ProjectedEdge, ProjectionInputs

__all__ = [
    "ProjectedEdge",
    "ProjectionInputs",
    "build_projection_inputs",
    "project_link_rows",
]
