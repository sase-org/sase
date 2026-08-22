"""Stateful adapter over artifact-link sidecars, beads, and aggregates."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
import fcntl
from pathlib import Path
from typing import Any

from sase.agents_sync.io import atomic_write_json
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_files import artifact_link_lock_path
from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    BEAD_KIND,
    artifact_link_aggregate_path,
    canonicalize_artifact_link_ref,
    empty_artifact_link_aggregate,
    kind_of_ref,
    pair_matches,
    read_artifact_link_index,
    read_json_object,
    row_touches,
    sidecar_index_path,
    sidecar_kind_for_role,
    unique_rows,
    upsert_artifact_link_rows,
    validate_artifact_link_row,
    writes_sidecar_json,
)
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR
from sase.sdd.store import SddStore, document_sidecar_roles


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


@dataclass(frozen=True)
class ArtifactLinkStore:
    """Kind-native adapter over sidecar ``links/`` JSON plus the aggregate."""

    project_key: str
    sidecar_roots: Mapping[str, Path]
    beads_dir: Path | None = None
    sdd_store: SddStore | None = None

    def __post_init__(self) -> None:
        key = self.project_key.strip()
        artifact_link_aggregate_path(key)
        object.__setattr__(self, "project_key", key)

    @classmethod
    def from_sdd_store(cls, store: SddStore, project_key: str) -> ArtifactLinkStore:
        """Build an adapter from one resolved SDD store."""

        roots: dict[str, Path] = {}
        roles = document_sidecar_roles(store.split_sidecar_roles(), include_plans=True)
        for role in roles:
            try:
                roots[sidecar_kind_for_role(role)] = (
                    store.repo_root_for_kind(role).expanduser().resolve(strict=False)
                )
            except Exception:  # noqa: BLE001 - skip unresolved sidecars
                continue
        beads_dir = store.beads_dir
        if beads_dir is not None:
            resolved = beads_dir.expanduser().resolve(strict=False)
            beads_dir = resolved if resolved.is_dir() else None
        return cls(
            project_key=project_key,
            sidecar_roots=roots,
            beads_dir=beads_dir,
            sdd_store=store,
        )

    def sidecar_root_for(self, artifact_ref: str) -> Path | None:
        """Return the sidecar root that should store *artifact_ref*, if any."""

        if not writes_sidecar_json(artifact_ref):
            return None
        return self.sidecar_roots.get(kind_of_ref(artifact_ref))

    def _is_aggregate_only(self, row: Mapping[str, Any]) -> bool:
        """Return whether neither endpoint owns sidecar ``links/`` JSON."""

        source = str(row.get("source_ref") or "")
        target = str(row.get("target_ref") or "")
        return (
            self.sidecar_root_for(source) is None
            and self.sidecar_root_for(target) is None
        )

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
        result = dict(
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
            if row_touches(row, canonical)
        )

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
            # Bead-sourced rows are rebuilt from the event store. Keep
            # aggregate-only incoming rows whose source is not a bead,
            # notably ``agent:`` citations and audited reads of a bead.
            if self._is_aggregate_only(row) and not (
                self.beads_dir is not None
                and kind_of_ref(str(row.get("source_ref") or "")) == BEAD_KIND
            ):
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

    def _upsert_sidecar(
        self, artifact_ref: str, incoming: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        root = self.sidecar_root_for(artifact_ref)
        if root is None:
            return None
        canonical = canonicalize_artifact_link_ref(artifact_ref)
        path = sidecar_index_path(root, canonical)
        with locked_file(artifact_link_lock_path(path), fcntl.LOCK_EX):
            index = read_artifact_link_index(path, artifact_ref=canonical)
            outcome = upsert_artifact_link_rows(index["rows"], incoming)
            if str(outcome.get("kind") or "") == "unchanged" and path.is_file():
                return {**outcome, "changed_indexes": ()}
            atomic_write_json(
                path,
                {
                    "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                    "artifact_ref": canonical,
                    "rows": outcome["rows"],
                },
            )
        return {**outcome, "changed_indexes": (path,)}

    def _remove_sidecar_rows(
        self,
        artifact_ref: str,
        *,
        source: str,
        target: str,
        relation: str | None,
    ) -> tuple[list[dict[str, Any]], Path | None]:
        root = self.sidecar_root_for(artifact_ref)
        if root is None:
            return [], None
        canonical = canonicalize_artifact_link_ref(artifact_ref)
        path = sidecar_index_path(root, canonical)
        with locked_file(artifact_link_lock_path(path), fcntl.LOCK_EX):
            if not path.is_file():
                return [], None
            index = read_artifact_link_index(path, artifact_ref=canonical)
            kept: list[dict[str, Any]] = []
            dropped: list[dict[str, Any]] = []
            for row in index.get("rows", []):
                if pair_matches(row, source=source, target=target, relation=relation):
                    dropped.append(dict(row))
                else:
                    kept.append(dict(row))
            if dropped:
                atomic_write_json(
                    path,
                    {
                        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                        "artifact_ref": canonical,
                        "rows": kept,
                    },
                )
                return dropped, path
        return dropped, None

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
                if pair_matches(
                    raw, source=source, target=target, relation=relation
                ) and self._is_aggregate_only(raw):
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

    def _upsert_bead(self, incoming: Mapping[str, Any]) -> dict[str, Any] | None:
        if self.beads_dir is None:
            return None
        from sase.sdd.artifact_link_beads import (
            add_bead_endpoint_link,
            bead_id_from_ref,
        )

        issue_id = bead_id_from_ref(str(incoming["source_ref"]))
        if issue_id is None:
            return None
        created_at = str(incoming.get("created_at") or "").strip() or None
        payload = add_bead_endpoint_link(
            self.beads_dir,
            issue_id=issue_id,
            target_ref=str(incoming["target_ref"]),
            relation=str(incoming["relation"]),
            description=str(incoming["description"]),
            origin=str(incoming.get("origin") or "manual"),
            now=created_at,
        )
        return {
            "kind": "added" if payload.get("changed") else "unchanged",
            "row": dict(incoming),
            "rows": [dict(row) for row in payload.get("rows", [])],
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
        seen_ids: set[str] = set()
        for ref, other in ((source, target), (target, source)):
            issue_id = bead_id_from_ref(ref)
            if issue_id is None or issue_id in seen_ids:
                continue
            seen_ids.add(issue_id)
            remove_bead_endpoint_link(
                self.beads_dir,
                issue_id=issue_id,
                target_ref=other,
                relation=relation,
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

    def _write_aggregate(self, document: Mapping[str, Any]) -> None:
        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            atomic_write_json(path, dict(document))

    def _iter_sidecar_rows(self) -> Iterable[dict[str, Any]]:
        seen_roots: set[Path] = set()
        for kind, root in self.sidecar_roots.items():
            resolved = root.expanduser().resolve(strict=False)
            if resolved in seen_roots or not resolved.is_dir():
                continue
            seen_roots.add(resolved)
            links_root = resolved / REFERENCED_BY_LINKS_DIR
            if not links_root.is_dir():
                continue
            for path in sorted(links_root.rglob("*.json")):
                relative = path.relative_to(links_root).as_posix()
                if not relative.endswith(".json"):
                    continue
                artifact_ref = f"{kind}:{relative[: -len('.json')]}"
                index = read_artifact_link_index(path, artifact_ref=artifact_ref)
                for row in index.get("rows", []):
                    if isinstance(row, dict):
                        yield dict(row)


def resolve_artifact_link_store(cwd: Path | None = None) -> ArtifactLinkStore:
    """Resolve the current checkout's artifact-link adapter."""

    from sase.sdd.checkout_anchor import resolve_checkout_anchor
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    start = (cwd or Path.cwd()).expanduser().resolve(strict=False)
    project_key = resolve_artifact_link_project_key(start)
    if not project_key:
        raise RuntimeError("could not resolve the current project for artifact links")
    anchor = resolve_checkout_anchor(start)
    primary_root, workspace_num = workspace_context_for_plan_resolution(
        anchor.primary_root
    )
    store = resolve_sdd_store(primary_root, workspace_num)
    return ArtifactLinkStore.from_sdd_store(store, project_key)


def resolve_artifact_link_project_key(
    cwd: Path | None = None,
    *,
    fallback: str | None = None,
) -> str | None:
    """Resolve *cwd* or *fallback* to a canonical ProjectSpec key."""

    start = (cwd or Path.cwd()).expanduser().resolve(strict=False)
    candidates: list[tuple[str, bool]] = []
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(start))
    except Exception:  # noqa: BLE001 - CLI resolution is best-effort
        found = None
    if found is not None:
        marker = found[1]
        if isinstance(marker.project_key, str) and marker.project_key.strip():
            candidates.append((marker.project_key, True))
        if isinstance(marker.project_name, str) and marker.project_name.strip():
            candidates.append((marker.project_name, False))
    if fallback:
        candidates.append((fallback, True))
    try:
        from sase.bead.project_name import infer_project_name_from_cwd

        inferred = infer_project_name_from_cwd(str(start))
    except Exception:  # noqa: BLE001 - CLI resolution is best-effort
        inferred = None
    if inferred:
        candidates.append((inferred, False))
    seen: set[str] = set()
    for candidate, allow_direct in candidates:
        ref = candidate.strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        resolved = _project_key_for_ref(ref, allow_direct=allow_direct)
        if resolved is not None:
            return resolved
    return None


def _project_key_for_ref(ref: str, *, allow_direct: bool) -> str | None:
    try:
        from sase.core.paths import sase_projects_dir
        from sase.core.project_lifecycle_facade import list_project_records
        from sase.core.project_lifecycle_wire import effective_project_name

        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception:  # noqa: BLE001 - fall back to direct key validation
        records = []

    folded = ref.casefold()
    for record in records:
        aliases = {alias.casefold() for alias in getattr(record, "aliases", ())}
        display = effective_project_name(record)
        if folded in {
            record.project_name.casefold(),
            display.casefold(),
            _project_provider_slug(record.project_name).casefold(),
            *aliases,
        }:
            return record.project_name

    if allow_direct and not records:
        try:
            artifact_link_aggregate_path(ref)
        except ValueError:
            return None
        return ref
    return None


def _project_provider_slug(project_key: str) -> str:
    if not project_key.startswith("gh_") or "__" not in project_key:
        return project_key
    owner, repository = project_key.removeprefix("gh_").split("__", 1)
    return f"{owner}/{repository}"
