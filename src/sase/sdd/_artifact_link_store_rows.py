"""Public row CRUD operations for :class:`ArtifactLinkStore`."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_store_support import (
    BEAD_KIND,
    canonicalize_artifact_link_ref,
    is_projected_row,
    kind_of_ref,
    pair_matches,
    read_artifact_link_index,
    row_touches,
    sidecar_index_path,
    unique_rows,
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
    _upsert_aggregate_row: Callable[[Mapping[str, Any]], dict[str, Any]]
    _remove_aggregate_rows: Callable[..., list[dict[str, Any]]]
    rebuild_aggregate: Callable[[], dict[str, Any]]
    load_aggregate: Callable[[], dict[str, Any]]

    def upsert_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
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
        rebuilt = self.rebuild_aggregate()
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
    ) -> tuple[dict[str, Any], ...]:
        """Return every stored row touching *artifact_ref*.

        When *bead_owned_rows* is supplied for a ``bead:`` ref, those rows are
        treated as the authoritative bead-owned neighborhood and the bead
        event store is not reduced again.
        """

        canonical = canonicalize_artifact_link_ref(artifact_ref)
        if bead_owned_rows is not None and kind_of_ref(canonical) == BEAD_KIND:
            return self._merge_bead_neighborhood(canonical, bead_owned_rows)
        root = self.sidecar_root_for(canonical)
        if root is not None:
            index = read_artifact_link_index(
                sidecar_index_path(root, canonical),
                artifact_ref=canonical,
            )
            return tuple(dict(row) for row in index.get("rows", []))
        if self.beads_dir is not None and kind_of_ref(canonical) == BEAD_KIND:
            return self._load_bead_rows(canonical)
        return tuple(
            dict(row)
            for row in self.load_aggregate().get("rows", [])
            if row_touches(row, canonical) and not is_projected_row(row)
        )
