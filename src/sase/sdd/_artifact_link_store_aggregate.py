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
    empty_artifact_link_aggregate,
    pair_matches,
    read_json_object,
    unique_rows,
    upsert_artifact_link_rows,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class ArtifactLinkStoreAggregateMixin:
    """Reads, writes, and rebuilds the project-wide aggregate document."""

    project_key: str
    _iter_sidecar_rows: Callable[[], Iterable[dict[str, Any]]]
    _iter_bead_rows: Callable[[], Iterable[dict[str, Any]]]
    _authoritative_source_was_consulted: Callable[[Mapping[str, Any]], bool]

    def load_aggregate(self) -> dict[str, Any]:
        """Read the project aggregate, or return an empty v2 document."""

        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
            if not path.is_file():
                return empty_artifact_link_aggregate()
            payload = read_json_object(path)
        if payload.get("schema_version") != ARTIFACT_LINK_ROW_SCHEMA_VERSION:
            raise RuntimeError(f"unsupported artifact link aggregate schema: {path}")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise RuntimeError("artifact link aggregate rows must be a list")
        return {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "rows": [dict(row) for row in rows if isinstance(row, dict)],
        }

    def preview_aggregate(self) -> dict[str, Any]:
        """Return the aggregate that a rebuild would write, without writing it."""

        collected = list(self._iter_sidecar_rows())
        collected.extend(self._iter_bead_rows())
        for row in self.load_aggregate().get("rows", []):
            # Carry forward rows whose authoritative source was not visible in
            # this workspace. Visible companion files and source-bead events are
            # enough evidence to prove a prior row was deleted; missing
            # companions in this clone are not.
            if not self._authoritative_source_was_consulted(row):
                collected.append(row)
        return {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "rows": unique_rows(collected),
        }

    def rebuild_aggregate(self) -> dict[str, Any]:
        """Rebuild ``artifact-links.json`` from sidecar JSON plus bead events."""

        document = self.preview_aggregate()
        self._write_aggregate(document)
        return document

    def _upsert_aggregate_row(self, incoming: Mapping[str, Any]) -> dict[str, Any]:
        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            current = empty_artifact_link_aggregate()
            if path.is_file():
                payload = read_json_object(path)
                rows = payload.get("rows")
                if isinstance(rows, list):
                    current["rows"] = [
                        dict(row) for row in rows if isinstance(row, dict)
                    ]
            outcome = upsert_artifact_link_rows(current["rows"], incoming)
            document = {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "rows": outcome["rows"],
            }
            atomic_write_json(path, document)
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
            if not path.is_file():
                return []
            payload = read_json_object(path)
            rows = payload.get("rows")
            if not isinstance(rows, list):
                return []
            kept: list[dict[str, Any]] = []
            dropped: list[dict[str, Any]] = []
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                if pair_matches(raw, source=source, target=target, relation=relation):
                    dropped.append(dict(raw))
                else:
                    kept.append(dict(raw))
            if dropped:
                atomic_write_json(
                    path,
                    {
                        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                        "rows": kept,
                    },
                )
        return dropped

    def _write_aggregate(self, document: Mapping[str, Any]) -> None:
        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            atomic_write_json(path, dict(document))
