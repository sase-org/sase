"""Project aggregate (``artifact-links.json``) read/write helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import fcntl
from typing import TYPE_CHECKING, Any

from sase.agents_sync.io import atomic_write_json
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    artifact_link_aggregate_path,
    pair_matches,
    project_aggregate_rows,
    read_aggregate_document,
    unique_rows,
    upsert_artifact_link_rows,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# Bounded retries for the preview-then-write race: a chop and a workspace can
# both finish scanning around the same moment, and a loser must merge against
# the generation the winner just wrote rather than clobber it.
_MAX_AGGREGATE_WRITE_ATTEMPTS = 5


class ArtifactLinkStoreAggregateMixin:
    """Reads, writes, and rebuilds the project-wide aggregate document."""

    project_key: str
    _iter_sidecar_rows: Callable[[], Iterable[dict[str, Any]]]
    _iter_bead_rows: Callable[[], Iterable[dict[str, Any]]]
    _authoritative_source_was_consulted: Callable[[Mapping[str, Any]], bool]
    _authoritative_source_was_consulted_for_pass: Callable[
        [], Callable[[Mapping[str, Any]], bool]
    ]
    projected_rows: Callable[[], tuple[dict[str, Any], ...]]

    def load_aggregate(self) -> dict[str, Any]:
        """Read the project aggregate, or return an empty v2 document."""

        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
            return read_aggregate_document(path)

    def preview_aggregate(self) -> dict[str, Any]:
        """Return the aggregate a rebuild would write, without writing it.

        Scans only this workspace's own sidecars and bead events --
        :meth:`preview_reconciled_aggregate` is the cross-workspace scan.
        Both route the scanned rows plus the on-disk prior rows through
        :func:`project_aggregate_rows`, the one place that decides which
        rows survive, so the two previews can disagree about which stores
        they saw but never about which of the seen rows to keep. The
        projection layer's rows are recomputed fresh here too, never
        cross-workspace-reconciled.
        """

        prior = self.load_aggregate()
        collected = list(self._iter_sidecar_rows())
        collected.extend(self._iter_bead_rows())
        return {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "generation": prior["generation"],
            "rows": project_aggregate_rows(
                collected=collected,
                prior_rows=prior["rows"],
                authoritative_source_was_consulted=(
                    self._authoritative_source_was_consulted_for_pass()
                ),
                projected_rows=self.projected_rows(),
            ),
        }

    def rebuild_aggregate(self) -> dict[str, Any]:
        """Rebuild ``artifact-links.json`` from sidecar JSON plus bead events."""

        return self._write_merged_aggregate(self.preview_aggregate)

    def _write_merged_aggregate(
        self, compute_preview: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        """Write a freshly computed preview, retrying if it lost a race.

        ``compute_preview`` (``preview_aggregate`` or
        ``preview_reconciled_aggregate``) reads the on-disk generation as its
        merge base. If another writer -- a chop and a workspace, typically --
        advances the generation before this write lands, writing anyway would
        silently drop whatever they added, so a base mismatch is treated as a
        signal to recompute the preview against the new base and try again.
        Bounded so a pathologically hot file cannot loop forever; the last
        attempt writes regardless, against whatever generation is current at
        that point.
        """

        for attempt in range(_MAX_AGGREGATE_WRITE_ATTEMPTS):
            document = compute_preview()
            force = attempt == _MAX_AGGREGATE_WRITE_ATTEMPTS - 1
            written = self._write_aggregate_if_current(document, force=force)
            if written is not None:
                return written
        raise AssertionError("unreachable: the last attempt always forces the write")

    def _write_aggregate_if_current(
        self, document: Mapping[str, Any], *, force: bool = False
    ) -> dict[str, Any] | None:
        """CAS-write *document* if its base generation is still on disk.

        Returns the written document (its generation advanced by one) on
        success, or ``None`` when another writer has already advanced the
        generation -- the caller should recompute its preview and retry.
        *force* skips that check, for a bounded retry loop's last attempt.
        """

        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            current = read_aggregate_document(path)
            if not force and current["generation"] != document.get("generation"):
                return None
            payload = {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "generation": current["generation"] + 1,
                "rows": unique_rows(document.get("rows", [])),
            }
            atomic_write_json(path, payload)
            return payload

    def _upsert_aggregate_row(self, incoming: Mapping[str, Any]) -> dict[str, Any]:
        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            current = read_aggregate_document(path)
            outcome = upsert_artifact_link_rows(current["rows"], incoming)
            atomic_write_json(
                path,
                {
                    "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                    "generation": current["generation"] + 1,
                    "rows": outcome["rows"],
                },
            )
        return outcome

    def _remove_aggregate_rows(
        self,
        *,
        source: str,
        target: str,
        relation: str | None,
    ) -> list[dict[str, Any]]:
        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            current = read_aggregate_document(path)
            if not current["rows"]:
                return []
            kept: list[dict[str, Any]] = []
            dropped: list[dict[str, Any]] = []
            for raw in current["rows"]:
                if pair_matches(raw, source=source, target=target, relation=relation):
                    dropped.append(dict(raw))
                else:
                    kept.append(dict(raw))
            if dropped:
                atomic_write_json(
                    path,
                    {
                        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                        "generation": current["generation"] + 1,
                        "rows": kept,
                    },
                )
        return dropped

    def _write_aggregate(self, document: Mapping[str, Any]) -> None:
        """Replace the aggregate outright, bumping its generation.

        For callers that already derived the full row set they want written
        (the single-row edits above, and the ref-rename repair) rather than
        merging a stores-scan preview. Preview-based rebuilds go through
        :meth:`_write_merged_aggregate` instead, which refuses to clobber a
        concurrent writer's newer generation.
        """

        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            current_generation = read_aggregate_document(path)["generation"]
            atomic_write_json(
                path,
                {
                    "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                    "generation": current_generation + 1,
                    "rows": list(document.get("rows", [])),
                },
            )
