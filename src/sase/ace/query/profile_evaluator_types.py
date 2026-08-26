"""Row and evaluation-context types shared by the profile evaluator split."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.ace.query_profile import CompiledQueryProfile

type ProfileFieldValue = str | bool | int
type ArtifactQueryRowInput = Mapping[str, Any] | object


@dataclass(frozen=True, slots=True)
class ArtifactQueryRow:
    """Typed/coerced row consumed by the profile reference evaluator."""

    stable_id: str
    fields: Mapping[str, tuple[ProfileFieldValue, ...]]
    searchable_text: str
    predicates: frozenset[str] = frozenset()


@dataclass(slots=True)
class ArtifactQueryEvaluationContext:
    """Immutable per-corpus data shared by profile-driven per-row evaluation."""

    profile: CompiledQueryProfile
    rows: tuple[ArtifactQueryRow, ...]
    by_stable_id: Mapping[str, ArtifactQueryRow] = field(init=False)

    def __post_init__(self) -> None:
        self.by_stable_id = {row.stable_id: row for row in self.rows}
