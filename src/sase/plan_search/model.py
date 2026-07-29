"""Data models for ``sase plan search``.

These dataclasses mirror the Rust wire records (``crates/sase_core/src/plan/
wire.rs``): :class:`Plan` maps to ``PlanWire`` and :class:`PlanSearchMatch` maps
to ``PlanSearchMatchWire``. The Rust core owns discovery, filtering, and
ranking; Python only carries the results across the binding boundary and renders
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Plan:
    """A single discovered markdown plan artifact.

    ``source`` is ``"repo"`` for committed SDD artifacts and ``"local"`` for the
    machine-local archive. ``kind`` is ``"tale"``/``"epic"`` for canonical
    plans, ``"prompt"`` for a prompt snapshot, a configured document-sidecar
    role name for other repo documents, or the synthetic ``"local"`` kind for
    archive entries. ``relpath`` is relative to that document corpus root and
    always uses ``/`` separators.
    """

    source: str
    kind: str
    path: str
    relpath: str
    name: str
    title: str
    status: str
    created_at: str
    prompt_link: str
    summary: str
    body: str
    frontmatter: dict[str, str] = field(default_factory=dict)


@dataclass
class PlanSearchMatch:
    """A single ranked plan-search result.

    ``matched_fields`` lists the searchable field names hit by the query (empty
    in browse mode, when no query is supplied), and ``score`` is the numeric
    relevance (field-weighted + repo/recency boosts) Rust ranked the plan with.
    """

    plan: Plan
    matched_fields: list[str]
    score: float


__all__ = ["Plan", "PlanSearchMatch"]
