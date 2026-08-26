"""Bead event-store reads/writes for :class:`ArtifactLinkStore`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.sdd._artifact_link_store_support import pair_matches, row_touches, unique_rows

if TYPE_CHECKING:
    from collections.abc import Callable


class ArtifactLinkStoreBeadRowsMixin:
    """Reads and writes for bead-endpoint link events."""

    beads_dir: Path | None
    _iter_sidecar_rows: Callable[[], Iterable[dict[str, Any]]]
    load_aggregate: Callable[[], dict[str, Any]]
    _is_aggregate_only: Callable[[Mapping[str, Any]], bool]

    def _upsert_bead(self, incoming: Mapping[str, Any]) -> dict[str, Any] | None:
        if self.beads_dir is None:
            return None
        from sase.sdd.artifact_link_beads import (
            add_bead_endpoint_link,
            bead_id_from_ref,
        )

        source_ref = str(incoming["source_ref"])
        target_ref = str(incoming["target_ref"])
        relation = str(incoming["relation"])
        description = str(incoming["description"])
        origin = str(incoming.get("origin") or "manual")
        created_at = str(incoming.get("created_at") or "").strip() or None
        try:
            uses = int(incoming.get("uses", 1))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            uses = 1
        uses = uses if uses > 0 else 1

        writes: list[dict[str, Any]] = []
        source_issue_id = bead_id_from_ref(source_ref)
        if source_issue_id is not None:
            writes.append(
                add_bead_endpoint_link(
                    self.beads_dir,
                    issue_id=source_issue_id,
                    target_ref=target_ref,
                    relation=relation,
                    description=description,
                    origin=origin,
                    direction="out",
                    uses=uses,
                    now=created_at,
                )
            )
        target_issue_id = bead_id_from_ref(target_ref)
        if target_issue_id is not None and target_issue_id != source_issue_id:
            writes.append(
                add_bead_endpoint_link(
                    self.beads_dir,
                    issue_id=target_issue_id,
                    target_ref=source_ref,
                    relation=relation,
                    description=description,
                    origin=origin,
                    direction="in",
                    uses=uses,
                    now=created_at,
                )
            )
        if not writes:
            return None
        changed = any(bool(payload.get("changed")) for payload in writes)
        return {
            "kind": "added" if changed else "unchanged",
            "row": dict(incoming),
            "rows": [],
        }

    def _remove_bead_rows(
        self,
        *,
        source: str,
        target: str,
        relation: str | None,
    ) -> list[dict[str, Any]]:
        if self.beads_dir is None:
            return []
        from sase.sdd.artifact_link_beads import (
            bead_id_from_ref,
            remove_bead_endpoint_link,
        )

        before = [
            row
            for row in self._iter_bead_rows()
            if pair_matches(row, source=source, target=target, relation=relation)
        ]
        if not before:
            return []
        # A stored link's direction depends on which of source/target this
        # bead occupied when it was written, which this removal call cannot
        # know in advance (an undirected ``related`` edge, in particular,
        # may have landed as either). Try both directions per candidate
        # bead; a direction the bead does not actually hold is a no-op.
        seen: set[tuple[str, str]] = set()
        for ref, other in ((source, target), (target, source)):
            issue_id = bead_id_from_ref(ref)
            if issue_id is None:
                continue
            for direction in ("out", "in"):
                key = (issue_id, direction)
                if key in seen:
                    continue
                seen.add(key)
                remove_bead_endpoint_link(
                    self.beads_dir,
                    issue_id=issue_id,
                    target_ref=other,
                    relation=relation,
                    direction=direction,
                )
        return before

    def _load_bead_rows(self, artifact_ref: str) -> tuple[dict[str, Any], ...]:
        from sase.sdd.artifact_link_beads import bead_id_from_ref, rows_touching_bead

        issue_id = bead_id_from_ref(artifact_ref)
        if issue_id is None:
            return ()
        extra = [
            row for row in self._iter_sidecar_rows() if row_touches(row, artifact_ref)
        ]
        extra.extend(self._aggregate_only_rows_touching(artifact_ref))
        return rows_touching_bead(
            self._list_bead_issues(),
            issue_id,
            extra_rows=extra,
        )

    def _merge_bead_neighborhood(
        self,
        artifact_ref: str,
        bead_owned_rows: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        collected = [dict(row) for row in bead_owned_rows]
        collected.extend(
            row for row in self._iter_sidecar_rows() if row_touches(row, artifact_ref)
        )
        collected.extend(self._aggregate_only_rows_touching(artifact_ref))
        return tuple(unique_rows(collected))

    def _aggregate_only_rows_touching(self, artifact_ref: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.load_aggregate().get("rows", [])
            if self._is_aggregate_only(row) and row_touches(row, artifact_ref)
        ]

    def _iter_bead_rows(self) -> Iterable[dict[str, Any]]:
        if self.beads_dir is None:
            return
        from sase.sdd.artifact_link_beads import rows_from_bead_issues

        yield from rows_from_bead_issues(self._list_bead_issues())

    def _list_bead_issues(self) -> tuple[Any, ...]:
        if self.beads_dir is None:
            return ()
        from sase.bead.store_locator import open_bead_project_for_beads_dir

        with open_bead_project_for_beads_dir(self.beads_dir) as project:
            return tuple(project.list_issues())
