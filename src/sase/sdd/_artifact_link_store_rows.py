"""Public row CRUD operations for :class:`ArtifactLinkStore`."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_cutover_state import artifact_link_indexes_imported
from sase.sdd._artifact_link_store_support import (
    BEAD_KIND,
    artifact_link_row_identity,
    canonicalize_artifact_link_ref,
    is_projected_row,
    kind_of_ref,
    pair_matches,
    read_artifact_link_index,
    row_touches,
    sidecar_index_path,
    unique_rows,
    upsert_artifact_link_rows,
    validate_artifact_link_row,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class ArtifactLinkRemoval:
    """Rows dropped by :meth:`ArtifactLinkStore.remove_rows` plus commit inputs."""

    rows: tuple[dict[str, Any], ...]
    changed_indexes: tuple[Path, ...] = ()
    beads_changed: bool = False

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __bool__(self) -> bool:
        return bool(self.rows)


class ArtifactLinkStoreRowsMixin:
    """Top-level upsert/remove/read operations across every storage layer."""

    project_key: str
    sidecar_roots: Mapping[str, Path]
    beads_dir: Path | None
    sidecar_root_for: Callable[[str], Path | None]
    _is_aggregate_only: Callable[[Mapping[str, Any]], bool]
    _upsert_sidecar: Callable[[str, Mapping[str, Any]], dict[str, Any] | None]
    _remove_sidecar_rows: Callable[..., tuple[list[dict[str, Any]], Path | None]]
    _upsert_bead: Callable[[Mapping[str, Any]], dict[str, Any] | None]
    _remove_bead_rows: Callable[..., list[dict[str, Any]]]
    _merge_bead_neighborhood: Callable[
        [str, Sequence[Mapping[str, Any]]], tuple[dict[str, Any], ...]
    ]
    _load_bead_rows: Callable[[str], tuple[dict[str, Any], ...]]
    _iter_sidecar_rows: Callable[[], Iterable[dict[str, Any]]]
    _iter_bead_rows: Callable[[], Iterable[dict[str, Any]]]
    _upsert_aggregate_row: Callable[[Mapping[str, Any]], dict[str, Any]]
    _remove_aggregate_rows: Callable[..., list[dict[str, Any]]]
    load_aggregate: Callable[[], dict[str, Any]]
    artifact_link_event_snapshot: Callable[..., Any]

    if TYPE_CHECKING:

        def rebuild_aggregate(
            self,
            *,
            exclude_pending_event_ids: Iterable[str] = (),
        ) -> dict[str, Any]: ...

    def upsert_row(
        self,
        row: Mapping[str, Any],
        *,
        exclude_pending_event_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Write one validated row to sidecar JSON (when owned) and the aggregate."""

        validated = validate_artifact_link_row(row)
        outcome: dict[str, Any] | None = None
        changed_indexes: list[Path] = []
        for ref in (validated["source_ref"], validated["target_ref"]):
            written = self._upsert_sidecar(ref, validated)
            if written is not None:
                outcome = written
                changed_indexes.extend(written.get("changed_indexes") or ())
        beads_changed = False
        bead_written = self._upsert_bead(validated)
        if bead_written is not None:
            outcome = bead_written
            beads_changed = str(bead_written.get("kind") or "") != "unchanged"
        elif self._is_aggregate_only(validated):
            outcome = self._upsert_aggregate_row(validated)
        rebuilt = self.rebuild_aggregate(
            exclude_pending_event_ids=exclude_pending_event_ids,
        )
        result: dict[str, Any] = dict(
            outcome
            or {
                "kind": "unchanged",
                "row": validated,
                "rows": list(rebuilt.get("rows", [])),
            }
        )
        result["changed_indexes"] = tuple(dict.fromkeys(changed_indexes))
        result["beads_changed"] = beads_changed
        return result

    def remove_rows(
        self,
        source_ref: str,
        target_ref: str,
        *,
        relation: str | None = None,
    ) -> ArtifactLinkRemoval:
        """Remove edges between *source_ref* and *target_ref*.

        Without *relation*, every stored edge between the pair is removed.
        With *relation*, only that slug is removed. Matching is undirected:
        A→B and B→A are both removed.
        """

        source = canonicalize_artifact_link_ref(source_ref)
        target = canonicalize_artifact_link_ref(target_ref)
        if relation is not None:
            relation = str(
                require_rust_binding("artifact_relation_lookup")(relation)["slug"]
            )
        matching = [
            row
            for row in self.load_aggregate().get("rows", [])
            if pair_matches(row, source=source, target=target, relation=relation)
        ]
        if matching and all(is_projected_row(row) for row in matching):
            rule_ids = sorted({str(row.get("created_by") or "") for row in matching})
            raise ValueError(
                f"{source} <-> {target} is recomputed by {', '.join(rule_ids)}, not "
                "stored -- deleting it here would not stop the next rebuild from "
                "putting it straight back"
            )
        dropped: list[dict[str, Any]] = []
        changed_indexes: list[Path] = []
        for ref in (source, target):
            removed, changed = self._remove_sidecar_rows(
                ref, source=source, target=target, relation=relation
            )
            dropped.extend(removed)
            if changed is not None:
                changed_indexes.append(changed)
        bead_dropped = self._remove_bead_rows(
            source=source, target=target, relation=relation
        )
        dropped.extend(bead_dropped)
        dropped.extend(
            self._remove_aggregate_rows(source=source, target=target, relation=relation)
        )
        self.rebuild_aggregate()
        return ArtifactLinkRemoval(
            rows=tuple(unique_rows(dropped)),
            changed_indexes=tuple(dict.fromkeys(changed_indexes)),
            beads_changed=bool(bead_dropped),
        )

    def load_artifact_rows(
        self,
        artifact_ref: str,
        *,
        bead_owned_rows: Sequence[Mapping[str, Any]] | None = None,
        exclude_pending_event_ids: Iterable[str] = (),
    ) -> tuple[dict[str, Any], ...]:
        """Return every stored row touching *artifact_ref*.

        When *bead_owned_rows* is supplied for a ``bead:`` ref, those rows are
        treated as the authoritative bead-owned neighborhood and the bead
        event store is not reduced again.
        """

        canonical = canonicalize_artifact_link_ref(artifact_ref)
        if bead_owned_rows is not None and kind_of_ref(canonical) == BEAD_KIND:
            return self._merge_bead_neighborhood(canonical, bead_owned_rows)
        event_snapshot = self.artifact_link_event_snapshot(
            include_pending=True,
            strict=True,
            exclude_pending_event_ids=exclude_pending_event_ids,
        )
        durable_event_rows = tuple(
            row for row in event_snapshot.durable_rows if row_touches(row, canonical)
        )
        event_rows = tuple(
            row for row in event_snapshot.rows if row_touches(row, canonical)
        )
        if self._legacy_indexes_imported():
            if self.beads_dir is not None and kind_of_ref(canonical) == BEAD_KIND:
                bead_rows = _rows_not_covered_by_events(
                    self._load_bead_rows(canonical),
                    event_snapshot,
                )
                return _merge_event_rows(bead_rows, event_rows)
            return event_rows
        root = self.sidecar_root_for(canonical)
        if root is not None:
            index = read_artifact_link_index(
                sidecar_index_path(root, canonical),
                artifact_ref=canonical,
            )
            legacy_rows = tuple(dict(row) for row in index.get("rows", []))
            self._reject_legacy_event_overlap(legacy_rows, durable_event_rows)
            return _merge_event_rows(legacy_rows, event_rows)
        if self.beads_dir is not None and kind_of_ref(canonical) == BEAD_KIND:
            bead_rows = _rows_not_covered_by_events(
                self._load_bead_rows(canonical),
                event_snapshot,
            )
            return _merge_event_rows(bead_rows, event_rows)
        aggregate_rows = tuple(
            dict(row)
            for row in self.load_aggregate().get("rows", [])
            if row_touches(row, canonical) and not is_projected_row(row)
        )
        return _merge_event_rows(aggregate_rows, event_rows)

    def load_durable_rows(self) -> tuple[dict[str, Any], ...]:
        """Return every row owned by sidecars, event objects, pending events, or beads.

        This is the store-truth read path for callers that need to audit the
        machine-local aggregate rather than trusting it.
        """

        return self._load_store_truth_rows(include_pending=True)

    def _load_store_truth_rows(
        self,
        *,
        include_pending: bool,
        exclude_pending_event_ids: Iterable[str] = (),
    ) -> tuple[dict[str, Any], ...]:
        legacy_rows = tuple(self._iter_sidecar_rows())
        bead_rows = tuple(self._iter_bead_rows())
        event_snapshot = self.artifact_link_event_snapshot(
            include_pending=include_pending,
            strict=True,
            exclude_pending_event_ids=exclude_pending_event_ids,
        )
        if self._legacy_indexes_imported():
            event_rows = (
                event_snapshot.rows if include_pending else event_snapshot.durable_rows
            )
            bead_rows = _rows_not_covered_by_events(bead_rows, event_snapshot)
            return tuple(unique_rows((*bead_rows, *event_rows)))
        self._reject_legacy_event_overlap(legacy_rows, event_snapshot.durable_rows)
        event_rows = (
            event_snapshot.rows if include_pending else event_snapshot.durable_rows
        )
        bead_rows = _rows_not_covered_by_events(bead_rows, event_snapshot)
        base_rows = (*legacy_rows, *bead_rows)
        if not include_pending:
            return tuple(unique_rows((*base_rows, *event_rows)))
        return _merge_event_rows(base_rows, event_rows)

    def _load_sidecar_truth_rows(
        self,
        *,
        include_pending: bool,
        exclude_pending_event_ids: Iterable[str] = (),
    ) -> tuple[dict[str, Any], ...]:
        legacy_rows = tuple(self._iter_sidecar_rows())
        event_snapshot = self.artifact_link_event_snapshot(
            include_pending=include_pending,
            strict=True,
            exclude_pending_event_ids=exclude_pending_event_ids,
        )
        if self._legacy_indexes_imported():
            return tuple(
                unique_rows(
                    event_snapshot.rows
                    if include_pending
                    else event_snapshot.durable_rows
                )
            )
        self._reject_legacy_event_overlap(legacy_rows, event_snapshot.durable_rows)
        if not include_pending:
            return tuple(unique_rows((*legacy_rows, *event_snapshot.durable_rows)))
        return _merge_event_rows(legacy_rows, event_snapshot.rows)

    def _load_event_rows(
        self,
        *,
        include_pending: bool,
        exclude_pending_event_ids: Iterable[str] = (),
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row)
            for row in self.artifact_link_event_snapshot(
                include_pending=include_pending,
                strict=True,
                exclude_pending_event_ids=exclude_pending_event_ids,
            ).rows
        )

    def _reject_legacy_event_overlap(
        self,
        legacy_rows: Iterable[Mapping[str, Any]],
        event_rows: Iterable[Mapping[str, Any]],
    ) -> None:
        if self._legacy_indexes_imported():
            return
        legacy_identities = {artifact_link_row_identity(row) for row in legacy_rows}
        event_identities = {artifact_link_row_identity(row) for row in event_rows}
        overlap = sorted(legacy_identities.intersection(event_identities))
        if not overlap:
            return
        formatted = ", ".join(" ".join(identity) for identity in overlap[:4])
        if len(overlap) > 4:
            formatted += f", ... plus {len(overlap) - 4} more"
        raise RuntimeError(
            "artifact-link legacy/event overlap rejected before event cutover: "
            + formatted
        )

    def _legacy_indexes_imported(self) -> bool:
        return artifact_link_indexes_imported(
            self.sidecar_roots,
            project_key=self.project_key,
        )


def _merge_event_rows(
    base_rows: Iterable[Mapping[str, Any]],
    event_rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows = unique_rows(base_rows)
    for event_row in event_rows:
        outcome = upsert_artifact_link_rows(rows, event_row)
        rows = [dict(row) for row in outcome.get("rows", []) if isinstance(row, dict)]
    return tuple(rows)


def _rows_not_covered_by_events(
    rows: Iterable[Mapping[str, Any]],
    event_snapshot: Any,
) -> tuple[dict[str, Any], ...]:
    """Keep bead projection rows only until immutable event truth covers them."""

    return tuple(dict(row) for row in rows if not event_snapshot.covers_row(row))
