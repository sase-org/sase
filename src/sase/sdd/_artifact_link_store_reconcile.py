"""Cross-workspace aggregate reconciliation for :class:`ArtifactLinkStore`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifact_ref_models import ArtifactRefContext

from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    BEAD_KIND,
    is_projected_row,
    kind_of_ref,
    project_aggregate_rows,
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
    _write_merged_aggregate: Callable[[Callable[[], dict[str, Any]]], dict[str, Any]]
    _iter_sidecar_rows: Callable[[], Iterable[dict[str, Any]]]
    _iter_bead_rows: Callable[[], Iterable[dict[str, Any]]]
    _authoritative_source_was_consulted: Callable[[Mapping[str, Any]], bool]
    _authoritative_source_was_consulted_for_pass: Callable[
        [Iterable[ArtifactLinkStore]], Callable[[Mapping[str, Any]], bool]
    ]
    _upsert_bead: Callable[[Mapping[str, Any]], dict[str, Any] | None]
    projected_rows: Callable[[], tuple[dict[str, Any], ...]]

    def durable_sidecar_rows(self) -> tuple[dict[str, Any], ...]:
        """Return sidecar rows whose agent endpoints have published.

        This filter serves the *publication* decision only: which rows are
        safe to hand another machine over the outbox. The local read-model
        aggregate must never apply it -- see :func:`project_aggregate_rows`
        and :meth:`preview_reconciled_aggregate`, which route around it
        deliberately so a row this workspace durably holds stays visible
        locally even when its agent endpoint has not published anywhere
        else.
        """

        context = self._resolved_pass_context()
        cache: dict[str, bool] = {}
        deduped = unique_rows(
            row
            for store in self._iter_reconciliation_stores()
            for row in self._iter_reconciliation_sidecar_rows(store)
        )
        return tuple(
            row
            for row in deduped
            if self._row_is_publishable(row, context=context, cache=cache)
        )

    def preview_reconciled_aggregate(self) -> dict[str, Any]:
        """Return the cross-workspace aggregate reconciliation result.

        Scans every visible workspace's sidecars and bead events, then
        routes the collected rows plus the on-disk prior rows through the
        same :func:`project_aggregate_rows` call :meth:`preview_aggregate`
        uses to decide which rows survive: this pass and that one may see a
        different set of stores, never a different keep/drop rule for what
        they both see. The projection layer's rows come from this
        workspace alone, exactly as :meth:`preview_aggregate` computes them.
        """

        prior = self.load_aggregate()
        collected: list[dict[str, Any]] = []
        stores = tuple(self._iter_reconciliation_stores())
        for store in stores:
            collected.extend(self._iter_reconciliation_sidecar_rows(store))
            collected.extend(self._iter_reconciliation_bead_rows(store))
        return {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "generation": prior["generation"],
            "rows": project_aggregate_rows(
                collected=collected,
                prior_rows=prior["rows"],
                authoritative_source_was_consulted=(
                    self._authoritative_source_was_consulted_for_pass(stores)
                ),
                projected_rows=self.projected_rows(),
            ),
        }

    def reconcile_aggregate(self) -> dict[str, Any]:
        """Reconcile the aggregate with all visible workspace sidecar rows."""

        return self._write_merged_aggregate(self.preview_reconciled_aggregate)

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
            if is_projected_row(row):
                continue
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
        cache: dict[str, bool] | None = None,
    ) -> bool:
        """Return whether agent endpoints in *row* have been published."""

        for ref in (str(row.get("source_ref") or ""), str(row.get("target_ref") or "")):
            if kind_of_ref(ref) != "agent":
                continue
            published = None if cache is None else cache.get(ref)
            if published is None:
                published = self._agent_ref_is_published(ref, context=context)
                if cache is not None:
                    cache[ref] = published
            if not published:
                return False
        return True

    def _agent_ref_is_published(
        self,
        ref: str,
        *,
        context: ArtifactRefContext | None,
    ) -> bool:
        try:
            from sase.artifact_cli.references import resolve_cli_reference

            result = resolve_cli_reference(ref, context=context)
        except Exception:  # noqa: BLE001 - unresolved agents stay local.
            return False
        return result.resolution.status in {"exact", "drifted", "vcs_backed"}

    def _resolved_pass_context(self) -> ArtifactRefContext | None:
        """Resolve the artifact-ref context once for a reconciliation pass.

        ``_artifact_ref_context_for_store`` returns ``None`` when the store's
        roots carry no workspace marker, which is always true for the
        housekeeping chop's primary-checkout cwd. Falling back here, once,
        keeps a ``None`` context from ever reaching ``resolve_cli_reference``
        -- which would otherwise rebuild this same context from scratch for
        every agent-ref row in the pass.
        """

        context = self._artifact_ref_context_for_store()
        if context is not None:
            return context
        try:
            from sase.artifact_ref_context import launch_artifact_ref_context

            return launch_artifact_ref_context(is_home_mode=False)
        except Exception:  # noqa: BLE001 - a slow pass beats a failed reconcile.
            return None

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
