"""Row-level drift summaries for artifact-link indexes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.sdd._artifact_link_store_support import unique_rows

_ROW_LIMIT = 10
_SIGNATURE_FIELDS = (
    "source_ref",
    "relation",
    "target_ref",
    "description",
    "origin",
    "created_by",
    "created_at",
    "uses",
)


@dataclass(frozen=True)
class ArtifactLinkDiffRow:
    """Human-scale identity for one differing artifact-link row."""

    source_ref: str
    relation: str
    target_ref: str
    origin: str


@dataclass(frozen=True)
class ArtifactLinkDiffSide:
    """One side of an artifact-link index drift report."""

    total: int = 0
    by_relation: tuple[tuple[str, int], ...] = ()
    by_origin: tuple[tuple[str, int], ...] = ()
    by_endpoint_kind: tuple[tuple[str, int], ...] = ()
    rows: tuple[ArtifactLinkDiffRow, ...] = ()


@dataclass(frozen=True)
class ArtifactLinkIndexDrift:
    """Rows missing from or extra in an artifact-link index."""

    missing: ArtifactLinkDiffSide = field(default_factory=ArtifactLinkDiffSide)
    extra: ArtifactLinkDiffSide = field(default_factory=ArtifactLinkDiffSide)

    @property
    def has_drift(self) -> bool:
        return self.missing.total > 0 or self.extra.total > 0


def build_artifact_link_index_drift(
    *,
    expected_rows: Iterable[Mapping[str, Any]],
    indexed_rows: Iterable[Mapping[str, Any]],
    row_limit: int = _ROW_LIMIT,
) -> ArtifactLinkIndexDrift:
    """Compare expected read-model rows with rows present in an index."""

    expected = _rows_by_signature(unique_rows(expected_rows))
    indexed = _rows_by_signature(unique_rows(indexed_rows))
    missing = _sorted_rows(
        expected[signature] for signature in set(expected) - set(indexed)
    )
    extra = _sorted_rows(
        indexed[signature] for signature in set(indexed) - set(expected)
    )
    return ArtifactLinkIndexDrift(
        missing=_summarize_side(missing, row_limit=row_limit),
        extra=_summarize_side(extra, row_limit=row_limit),
    )


def format_artifact_link_index_drift(drift: ArtifactLinkIndexDrift) -> str:
    """Return a compact plain-text summary for doctor next steps."""

    if not drift.has_drift:
        return "artifact-links aggregate matches expected rows"
    parts: list[str] = []
    if drift.missing.total:
        parts.append(
            f"missing {drift.missing.total} row(s)"
            f" ({_format_pairs(drift.missing.by_relation)})"
        )
    if drift.extra.total:
        parts.append(
            f"extra {drift.extra.total} row(s)"
            f" ({_format_pairs(drift.extra.by_relation)})"
        )
    return "; ".join(parts)


def _rows_by_signature(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, ...], dict[str, Any]]:
    return {_row_signature(row): dict(row) for row in rows}


def _row_signature(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(_field_value(row, field_name) for field_name in _SIGNATURE_FIELDS)


def _field_value(row: Mapping[str, Any], field_name: str) -> str:
    if field_name == "uses":
        try:
            return str(int(row.get("uses") or 0))
        except (TypeError, ValueError):
            return "0"
    return str(row.get(field_name) or "")


def _sorted_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in rows), key=_row_sort_key)


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("source_ref") or ""),
        str(row.get("relation") or ""),
        str(row.get("target_ref") or ""),
        str(row.get("origin") or ""),
        str(row.get("created_at") or ""),
        str(row.get("created_by") or ""),
    )


def _summarize_side(
    rows: list[dict[str, Any]], *, row_limit: int
) -> ArtifactLinkDiffSide:
    relation_counts = Counter(str(row.get("relation") or "unknown") for row in rows)
    origin_counts = Counter(str(row.get("origin") or "unknown") for row in rows)
    endpoint_kind_counts: Counter[str] = Counter()
    for row in rows:
        source_kind = _ref_kind(str(row.get("source_ref") or ""))
        target_kind = _ref_kind(str(row.get("target_ref") or ""))
        endpoint_kind_counts[f"source:{source_kind}"] += 1
        endpoint_kind_counts[f"target:{target_kind}"] += 1
    return ArtifactLinkDiffSide(
        total=len(rows),
        by_relation=_counter_items(relation_counts),
        by_origin=_counter_items(origin_counts),
        by_endpoint_kind=_counter_items(endpoint_kind_counts),
        rows=tuple(
            ArtifactLinkDiffRow(
                source_ref=str(row.get("source_ref") or ""),
                relation=str(row.get("relation") or ""),
                target_ref=str(row.get("target_ref") or ""),
                origin=str(row.get("origin") or "unknown"),
            )
            for row in rows[: max(row_limit, 0)]
        ),
    )


def _ref_kind(ref: str) -> str:
    kind, separator, _rest = ref.partition(":")
    return kind if separator and kind else "unknown"


def _counter_items(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(counter.items()))


def _format_pairs(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{name}: {count}" for name, count in values) or "none"


__all__ = [
    "ArtifactLinkDiffRow",
    "ArtifactLinkDiffSide",
    "ArtifactLinkIndexDrift",
    "build_artifact_link_index_drift",
    "format_artifact_link_index_drift",
]
