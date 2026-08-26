"""Cross-workspace aggregate reconciliation for :class:`ArtifactLinkStore`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifact_ref_models import ArtifactRefContext

from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    BEAD_KIND,
    kind_of_ref,
    unique_rows,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore


class ArtifactLinkStoreReconcileMixin:
    """Reconciles the project aggregate against every known workspace clone."""

    project_key: str
    sidecar_roots: Mapping[str, Path]
    beads_dir: Path | None
    load_aggregate: Callable[[], dict[str, Any]]
    rebuild_aggregate: Callable[[], dict[str, Any]]
    _write_aggregate: Callable[[Mapping[str, Any]], None]
    _iter_sidecar_rows: Callable[[], Iterable[dict[str, Any]]]
    _iter_bead_rows: Callable[[], Iterable[dict[str, Any]]]
    _upsert_bead: Callable[[Mapping[str, Any]], dict[str, Any] | None]

    def durable_sidecar_rows(self) -> tuple[dict[str, Any], ...]:
        """Return deduplicated publishable sidecar rows from known workspaces."""

        context = self._artifact_ref_context_for_store()
        return tuple(
            unique_rows(
                row
                for store in self._iter_reconciliation_stores()
                for row in self._iter_reconciliation_sidecar_rows(store)
                if self._row_is_publishable(row, context=context)
            )
        )

    def preview_reconciled_aggregate(self) -> dict[str, Any]:
        """Return the cross-workspace aggregate reconciliation result."""

        context = self._artifact_ref_context_for_store()
        collected: list[dict[str, Any]] = []
        for store in self._iter_reconciliation_stores():
            collected.extend(self._iter_reconciliation_sidecar_rows(store))
            collected.extend(self._iter_reconciliation_bead_rows(store))
        collected.extend(self.load_aggregate().get("rows", []))
        return {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "rows": unique_rows(
                row
                for row in collected
                if self._row_is_publishable(row, context=context)
            ),
        }

    def reconcile_aggregate(self) -> dict[str, Any]:
        """Reconcile the aggregate with all visible workspace sidecar rows."""

        document = self.preview_reconciled_aggregate()
        self._write_aggregate(document)
        return document

    def backfill_bead_endpoint_links(self) -> dict[str, int]:
        """Write the inbound event a one-sided write never produced.

        Scans every aggregate and sidecar row with a bead in the target
        position and writes that bead's ``direction="in"`` endpoint event
        when it does not already exist. Idempotent: a second run writes
        nothing. Returns candidate and written counts for reporting.
        """

        if self.beads_dir is None:
            return {"candidates": 0, "written": 0}
        candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in (
            *self.load_aggregate().get("rows", ()),
            *self._iter_sidecar_rows(),
        ):
            target = str(row.get("target_ref") or "")
            if kind_of_ref(target) != BEAD_KIND:
                continue
            source = str(row.get("source_ref") or "")
            relation = str(row.get("relation") or "")
            candidates[(source, relation, target)] = dict(row)
        written = 0
        for row in candidates.values():
            result = self._upsert_bead(row)
            if result is not None and str(result.get("kind") or "") == "added":
                written += 1
        if candidates:
            self.rebuild_aggregate()
        return {"candidates": len(candidates), "written": written}

    def _row_is_publishable(
        self,
        row: Mapping[str, Any],
        *,
        context: ArtifactRefContext | None = None,
    ) -> bool:
        """Return whether agent endpoints in *row* have been published."""

        for ref in (str(row.get("source_ref") or ""), str(row.get("target_ref") or "")):
            if kind_of_ref(ref) != "agent":
                continue
            try:
                from sase.artifact_cli.references import resolve_cli_reference

                result = resolve_cli_reference(ref, context=context)
            except Exception:  # noqa: BLE001 - unresolved agents stay local.
                return False
            if result.resolution.status not in {"exact", "drifted", "vcs_backed"}:
                return False
        return True

    def _artifact_ref_context_for_store(self) -> ArtifactRefContext | None:
        sdd_store = getattr(self, "sdd_store", None)
        if sdd_store is None:
            return None
        try:
            from sase.artifact_ref_context import artifact_ref_context
            from sase.workspace_provider import find_marker_from_cwd
        except Exception:  # noqa: BLE001 - fall back to cwd-based resolution.
            return None
        roots = (sdd_store.repo_root, *self.sidecar_roots.values())
        for root in roots:
            try:
                found = find_marker_from_cwd(str(root))
            except Exception:  # noqa: BLE001 - try the next visible root.
                continue
            if found is None:
                continue
            workspace_root, marker = found
            workspace_num = marker.workspace_num if marker.workspace_num > 0 else 1
            try:
                return artifact_ref_context(
                    workspace_root,
                    workspace_num,
                    project=self.project_key,
                )
            except Exception:  # noqa: BLE001 - fall back to cwd-based resolution.
                return None
        return None

    def _iter_reconciliation_stores(self) -> Iterable[ArtifactLinkStore]:
        """Yield known workspace stores for aggregate reconciliation."""

        seen: set[tuple[tuple[tuple[str, str], ...], str | None]] = set()

        def remember(store: ArtifactLinkStore) -> bool:
            identity = store._store_identity()
            if identity in seen:
                return False
            seen.add(identity)
            return True

        if remember(self):  # type: ignore[arg-type]
            yield self  # type: ignore[misc]
        try:
            from sase.repo_inventory import collect_repo_inventory
            from sase.sdd.store import resolve_sdd_store

            inventory = collect_repo_inventory(project=self.project_key)
        except Exception:  # noqa: BLE001 - reconciliation is best-effort.
            return
        for record in inventory.records:
            if record.kind != "primary" or record.project_key != self.project_key:
                continue
            for clone in record.clones:
                if not clone.exists:
                    continue
                try:
                    workspace_num = (
                        clone.workspace_num if clone.workspace_num > 0 else 1
                    )
                    sdd_store = resolve_sdd_store(Path(clone.path), workspace_num)
                    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore

                    store = ArtifactLinkStore.from_sdd_store(
                        sdd_store,
                        self.project_key,
                    )
                except Exception:  # noqa: BLE001 - absent clones prove nothing.
                    continue
                if remember(store):
                    yield store

    def _iter_reconciliation_sidecar_rows(
        self,
        store: ArtifactLinkStore,
    ) -> Iterable[dict[str, Any]]:
        try:
            yield from store._iter_sidecar_rows()
        except Exception:  # noqa: BLE001 - sibling clones prove nothing.
            if store._store_identity() == self._store_identity():
                raise

    def _iter_reconciliation_bead_rows(
        self,
        store: ArtifactLinkStore,
    ) -> Iterable[dict[str, Any]]:
        try:
            yield from store._iter_bead_rows()
        except Exception:  # noqa: BLE001 - sibling clones prove nothing.
            if store._store_identity() == self._store_identity():
                raise

    def _store_identity(self) -> tuple[tuple[tuple[str, str], ...], str | None]:
        roots = tuple(
            sorted(
                (
                    kind,
                    str(root.expanduser().resolve(strict=False)),
                )
                for kind, root in self.sidecar_roots.items()
            )
        )
        beads = (
            None
            if self.beads_dir is None
            else str(self.beads_dir.expanduser().resolve(strict=False))
        )
        return roots, beads
