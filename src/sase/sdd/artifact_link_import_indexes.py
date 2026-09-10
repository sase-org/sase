"""Import legacy artifact-link ``links/`` indexes into immutable events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import fcntl
import hashlib
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any, Literal

from sase.agents_sync.io import atomic_write_bytes, canonical_json_bytes
from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_commit import commit_artifact_link_indexes
from sase.sdd._artifact_link_cutover_state import (
    ArtifactLinkBaselineEventIdentity,
    ArtifactLinkCutoverImportIdentity,
    ArtifactLinkCutoverMarker,
    ArtifactLinkCutoverRole,
    artifact_link_cutover_marker_bytes,
    artifact_link_cutover_marker_path,
    build_artifact_link_cutover_marker_payload,
    inspect_artifact_link_cutover_markers,
    read_artifact_link_cutover_marker,
    role_for_artifact_link_kind,
)
from sase.sdd._artifact_link_event_canonical import (
    ARTIFACT_LINK_EVENT_LOCK_FILENAME,
    canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_store_support import (
    artifact_link_row_identity,
    read_artifact_link_index,
    sidecar_index_path,
    unique_rows,
    validate_artifact_link_row,
)
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR

if TYPE_CHECKING:
    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore


@dataclass(frozen=True, slots=True)
class _ArtifactLinkImportRole:
    """Frozen sidecar input for one role."""

    role: str
    kind: str
    root: Path
    head: str
    links_tree: str
    remote_url: str
    commit_time: str
    row_count: int = 0

    def marker_role(self) -> ArtifactLinkCutoverRole:
        return ArtifactLinkCutoverRole(
            role=self.role,
            kind=self.kind,
            head=self.head,
            links_tree=self.links_tree,
            remote_url=self.remote_url,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "commit_time": self.commit_time,
            "head": self.head,
            "kind": self.kind,
            "links_tree": self.links_tree,
            "remote_url": self.remote_url,
            "role": self.role,
            "root": str(self.root),
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class _ArtifactLinkIndexImportPlan:
    """Deterministic preview of one legacy-index import."""

    project_key: str
    roles: tuple[_ArtifactLinkImportRole, ...]
    rows: tuple[dict[str, Any], ...]
    duplicate_rows: int
    import_identity: ArtifactLinkCutoverImportIdentity
    baseline_event: dict[str, Any]
    baseline_event_identity: ArtifactLinkBaselineEventIdentity
    fenced_marker: ArtifactLinkCutoverMarker
    imported_marker: ArtifactLinkCutoverMarker

    @property
    def import_id(self) -> str:
        return self.import_identity.import_id

    @property
    def operation_id(self) -> str:
        return self.import_identity.operation_id

    @property
    def sidecar_roots(self) -> tuple[Path, ...]:
        return tuple(role.root for role in self.roles)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "baseline_event": {
                **self.baseline_event_identity.to_json_dict(),
                "operation_id": self.operation_id,
            },
            "duplicate_rows": self.duplicate_rows,
            "import": self.import_identity.to_json_dict(),
            "project_key": self.project_key,
            "roles": [role.to_json_dict() for role in self.roles],
            "rows": [dict(row) for row in self.rows],
            "unique_rows": len(self.rows),
        }


@dataclass(frozen=True, slots=True)
class ArtifactLinkIndexImportReport:
    """Result of a preview or apply run."""

    plan: _ArtifactLinkIndexImportPlan
    applied: bool
    already_imported: bool = False
    converted_outbox_entries: int = 0
    fenced_markers_changed: tuple[Path, ...] = ()
    event_paths: tuple[Path, ...] = ()
    imported_markers_changed: tuple[Path, ...] = ()
    aggregate_rows: int = 0
    publication_error: str | None = None
    skip_diagnostics: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "aggregate_rows": self.aggregate_rows,
            "already_imported": self.already_imported,
            "applied": self.applied,
            "converted_outbox_entries": self.converted_outbox_entries,
            "event_paths": [str(path) for path in self.event_paths],
            "fenced_markers_changed": [
                str(path) for path in self.fenced_markers_changed
            ],
            "imported_markers_changed": [
                str(path) for path in self.imported_markers_changed
            ],
            "plan": self.plan.to_json_dict(),
            "publication_error": self.publication_error,
            "skip_diagnostics": list(self.skip_diagnostics),
        }


def _plan_artifact_link_index_import(
    store: ArtifactLinkStore,
) -> _ArtifactLinkIndexImportPlan:
    """Build the deterministic legacy-index import plan without writing files."""

    frozen_roles = _frozen_roles(store)
    duplicate_rows = 0
    by_identity: dict[tuple[str, ...], dict[str, Any]] = {}
    by_identity_signature: dict[tuple[str, ...], bytes] = {}
    roles_with_counts: list[_ArtifactLinkImportRole] = []
    for frozen_role in frozen_roles:
        role_rows = _read_role_rows(frozen_role)
        role = replace(frozen_role, row_count=len(role_rows))
        roles_with_counts.append(role)
        for row in role_rows:
            identity = artifact_link_row_identity(row)
            signature = _logical_row_signature(row)
            existing_signature = by_identity_signature.get(identity)
            if existing_signature is None:
                by_identity_signature[identity] = signature
                by_identity[identity] = row
                continue
            duplicate_rows += 1
            if existing_signature != signature:
                raise RuntimeError(
                    "conflicting legacy artifact-link rows for identity: "
                    + " ".join(identity)
                )
            existing = by_identity[identity]
            if canonical_json_bytes(row) < canonical_json_bytes(existing):
                by_identity[identity] = row
    rows = tuple(
        dict(row)
        for row in sorted(
            by_identity.values(), key=lambda item: canonical_json_bytes(item)
        )
    )
    roles = tuple(roles_with_counts)
    _assert_marker_state_allows_plan(store, roles=roles)
    import_identity, baseline_event, baseline_identity = _baseline_import_identity(
        store.project_key,
        roles=roles,
        rows=rows,
    )
    _assert_baseline_reducer_parity(baseline_event, rows)
    fenced = _marker_for_plan(
        state="fenced",
        project_key=store.project_key,
        import_identity=import_identity,
        roles=roles,
        baseline_event=baseline_identity,
    )
    imported = _marker_for_plan(
        state="imported",
        project_key=store.project_key,
        import_identity=import_identity,
        roles=roles,
        baseline_event=baseline_identity,
    )
    return _ArtifactLinkIndexImportPlan(
        project_key=store.project_key,
        roles=roles,
        rows=rows,
        duplicate_rows=duplicate_rows,
        import_identity=import_identity,
        baseline_event=baseline_event,
        baseline_event_identity=baseline_identity,
        fenced_marker=fenced,
        imported_marker=imported,
    )


def import_artifact_link_indexes(
    store: ArtifactLinkStore,
    *,
    apply: bool = False,
    push_after_commit: bool | Literal["async"] | None = "async",
) -> ArtifactLinkIndexImportReport:
    """Preview or apply the legacy-index import."""

    if not apply:
        plan = _plan_artifact_link_index_import(store)
        return ArtifactLinkIndexImportReport(
            plan=plan,
            applied=False,
            aggregate_rows=len(store.load_aggregate().get("rows", [])),
        )

    lock_path = (
        sase_projects_dir() / store.project_key / ARTIFACT_LINK_EVENT_LOCK_FILENAME
    )
    with locked_file(lock_path, fcntl.LOCK_EX):
        plan = _plan_artifact_link_index_import(store)
        inspection = inspect_artifact_link_cutover_markers(
            store.sidecar_roots,
            project_key=store.project_key,
        )
        if inspection.imported and inspection.marker is not None:
            _assert_same_import(inspection.marker, plan.imported_marker)
            aggregate = store.rebuild_aggregate()
            return ArtifactLinkIndexImportReport(
                plan=plan,
                applied=True,
                already_imported=True,
                aggregate_rows=len(aggregate.get("rows", [])),
            )
        if inspection.fenced and inspection.marker is not None:
            _assert_same_import(inspection.marker, plan.fenced_marker)

        from sase.sdd.artifact_link_outbox import (
            convert_legacy_artifact_link_outbox_entries,
        )
        from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events

        converted = convert_legacy_artifact_link_outbox_entries(store.project_key)
        fenced_changed = _publish_marker(plan, plan.fenced_marker, push_after_commit)
        publish = publish_artifact_link_events(
            store,
            (plan.baseline_event,),
            push_after_commit=push_after_commit,
            mutation_origin="machine",
            already_locked=True,
            extra_roots=plan.sidecar_roots,
        )
        if publish.publication_error:
            raise RuntimeError(publish.publication_error)
        if publish.published != 1:
            diagnostic = (
                "\n".join(publish.skip_diagnostics)
                or "artifact-link baseline import event was not durable"
            )
            raise RuntimeError(diagnostic)
        _assert_baseline_durable(store, plan)
        imported_changed = _publish_marker(
            plan,
            plan.imported_marker,
            push_after_commit,
        )
        aggregate = store.rebuild_aggregate()
        return ArtifactLinkIndexImportReport(
            plan=plan,
            applied=True,
            converted_outbox_entries=converted,
            fenced_markers_changed=fenced_changed,
            event_paths=publish.event_paths,
            imported_markers_changed=imported_changed,
            aggregate_rows=len(aggregate.get("rows", [])),
            publication_error=publish.publication_error,
            skip_diagnostics=publish.skip_diagnostics,
        )


def artifact_link_legacy_links_tree_identity(root: Path) -> str:
    """Return the deterministic identity of a sidecar root's legacy links tree."""

    return _links_tree_identity(root.expanduser().resolve(strict=False))


def _frozen_roles(store: ArtifactLinkStore) -> tuple[_ArtifactLinkImportRole, ...]:
    inspection = inspect_artifact_link_cutover_markers(
        store.sidecar_roots,
        project_key=store.project_key,
    )
    if inspection.marker is not None:
        return _frozen_roles_from_marker(store, inspection.marker)

    roles: list[_ArtifactLinkImportRole] = []
    seen_roots: set[Path] = set()
    for kind, root in sorted(store.sidecar_roots.items()):
        resolved = root.expanduser().resolve(strict=False)
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        role = role_for_artifact_link_kind(str(kind))
        _assert_clean_git_root(resolved)
        roles.append(
            _ArtifactLinkImportRole(
                role=role,
                kind=str(kind),
                root=resolved,
                head=_git_output(resolved, "rev-parse", "HEAD"),
                links_tree=_links_tree_identity(resolved),
                remote_url=_remote_url_for(store, role, resolved),
                commit_time=_git_output(resolved, "show", "-s", "--format=%cI", "HEAD"),
            )
        )
    if not roles:
        raise RuntimeError(
            "artifact-link import requires at least one document sidecar"
        )
    return tuple(sorted(roles, key=lambda item: item.role))


def _frozen_roles_from_marker(
    store: ArtifactLinkStore,
    marker: ArtifactLinkCutoverMarker,
) -> tuple[_ArtifactLinkImportRole, ...]:
    roles: list[_ArtifactLinkImportRole] = []
    roots_by_kind = {
        kind: root.expanduser().resolve(strict=False)
        for kind, root in store.sidecar_roots.items()
    }
    for role in marker.roles:
        root = roots_by_kind.get(role.kind)
        if root is None:
            raise RuntimeError(
                f"artifact-link cutover marker references missing sidecar kind {role.kind}"
            )
        _assert_clean_git_root(root)
        current_links_tree = _links_tree_identity(root)
        if current_links_tree != role.links_tree:
            raise RuntimeError(
                f"artifact-link legacy links/ tree changed after import for {role.role}"
            )
        roles.append(
            _ArtifactLinkImportRole(
                role=role.role,
                kind=role.kind,
                root=root,
                head=role.head,
                links_tree=role.links_tree,
                remote_url=role.remote_url,
                commit_time=marker.import_identity.created_at,
            )
        )
    return tuple(sorted(roles, key=lambda item: item.role))


def _assert_clean_git_root(root: Path) -> None:
    if not (root / ".git").is_dir():
        raise RuntimeError(f"artifact-link import requires a git sidecar root: {root}")
    status = _git_output(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.strip():
        raise RuntimeError(
            f"artifact-link import requires a clean sidecar root: {root}"
        )


def _read_role_rows(role: _ArtifactLinkImportRole) -> tuple[dict[str, Any], ...]:
    links_root = role.root / REFERENCED_BY_LINKS_DIR
    if not links_root.is_dir():
        return ()
    rows: list[dict[str, Any]] = []
    for path in sorted(links_root.rglob("*.json")):
        if not path.is_file():
            continue
        relative = path.relative_to(links_root).as_posix()
        fallback_ref = f"{role.kind}:{relative[: -len('.json')]}"
        index = read_artifact_link_index(path, artifact_ref=fallback_ref)
        artifact_ref = str(index.get("artifact_ref") or fallback_ref)
        expected = sidecar_index_path(role.root, artifact_ref)
        if expected.resolve(strict=False) != path.resolve(strict=False):
            raise RuntimeError(f"artifact-link index path/ref mismatch: {path}")
        for row in index.get("rows", []):
            if not isinstance(row, Mapping):
                raise RuntimeError(f"artifact-link index row must be an object: {path}")
            rows.append(validate_artifact_link_row(row))
    return tuple(rows)


def _links_tree_identity(root: Path) -> str:
    links_root = root / REFERENCED_BY_LINKS_DIR
    files: list[dict[str, Any]] = []
    if links_root.is_dir():
        for path in sorted(links_root.rglob("*.json")):
            if not path.is_file():
                continue
            payload = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            )
    digest = hashlib.sha256(canonical_json_bytes({"files": files})).hexdigest()
    return f"sha256:{digest}"


def _remote_url_for(
    store: ArtifactLinkStore,
    role: str,
    root: Path,
) -> str:
    if store.sdd_store is not None:
        try:
            remote = store.sdd_store.remote_url_for_kind(role)
        except Exception:  # noqa: BLE001 - fall through to git config.
            remote = None
        if remote:
            return remote
    remote = _git_output(root, "config", "--get", "remote.origin.url", check=False)
    return remote or "<none>"


def _baseline_import_identity(
    project_key: str,
    *,
    roles: Sequence[_ArtifactLinkImportRole],
    rows: Sequence[Mapping[str, Any]],
) -> tuple[
    ArtifactLinkCutoverImportIdentity,
    dict[str, Any],
    ArtifactLinkBaselineEventIdentity,
]:
    source_head = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "project_key": project_key,
                    "roles": [role.marker_role().to_json_dict() for role in roles],
                }
            )
        ).hexdigest()
    )
    import_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "project_key": project_key,
                "roles": [role.marker_role().to_json_dict() for role in roles],
                "rows": [dict(row) for row in rows],
                "source_head": source_head,
            }
        )
    ).hexdigest()
    import_id = f"legacy-v2-links-{import_digest[:32]}"
    operation_id = str(
        require_rust_binding("artifact_link_event_canonicalize")(
            {
                "schema_version": int(
                    require_rust_binding("artifact_link_event_schema_version")()
                ),
                "project_key": project_key,
                "operation_id": hashlib.sha256(
                    canonical_json_bytes(
                        ["baseline-import", project_key, import_id, source_head]
                    )
                ).hexdigest()[:32],
                "created_by": "sase",
                "origin": "migrated",
                "created_at": _created_at_from_roles(roles),
                "kind": {
                    "type": "baseline-import",
                    "import_id": import_id,
                    "source_head": source_head,
                    "rows": [dict(row) for row in rows],
                },
            }
        )["operation_id"]
    )
    identity = ArtifactLinkCutoverImportIdentity(
        import_id=import_id,
        operation_id=operation_id,
        source_head=source_head,
        created_at=_created_at_from_roles(roles),
    )
    event = {
        "schema_version": int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        "project_key": project_key,
        "operation_id": operation_id,
        "created_by": "sase",
        "origin": "migrated",
        "created_at": identity.created_at,
        "kind": {
            "type": "baseline-import",
            "import_id": import_id,
            "source_head": source_head,
            "rows": [dict(row) for row in rows],
        },
    }
    event_object = canonical_artifact_link_event_object(event)
    return (
        identity,
        dict(event_object.event),
        ArtifactLinkBaselineEventIdentity(
            digest=event_object.digest,
            path=event_object.relative_path.as_posix(),
        ),
    )


def _created_at_from_roles(roles: Sequence[_ArtifactLinkImportRole]) -> str:
    timestamps: list[datetime] = []
    for role in roles:
        try:
            parsed = datetime.fromisoformat(role.commit_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        timestamps.append(parsed.astimezone(UTC))
    if not timestamps:
        return "1970-01-01T00:00:00Z"
    return max(timestamps).strftime("%Y-%m-%dT%H:%M:%SZ")


def _marker_for_plan(
    *,
    state: Literal["fenced", "imported"],
    project_key: str,
    import_identity: ArtifactLinkCutoverImportIdentity,
    roles: Sequence[_ArtifactLinkImportRole],
    baseline_event: ArtifactLinkBaselineEventIdentity,
) -> ArtifactLinkCutoverMarker:
    payload = build_artifact_link_cutover_marker_payload(
        state=state,
        project_key=project_key,
        event_store_schema_version=1,
        event_store_minimum_event_schema_version=int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        import_identity=import_identity,
        roles=[role.marker_role() for role in roles],
        baseline_event=baseline_event,
    )
    from sase.sdd._artifact_link_cutover_state import (
        parse_artifact_link_cutover_marker_payload,
    )

    return parse_artifact_link_cutover_marker_payload(payload)


def _publish_marker(
    plan: _ArtifactLinkIndexImportPlan,
    marker: ArtifactLinkCutoverMarker,
    push_after_commit: bool | Literal["async"] | None,
) -> tuple[Path, ...]:
    payload = marker.canonical_bytes
    changed_by_root: dict[Path, list[Path]] = {}
    changed: list[Path] = []
    for role in plan.roles:
        path = artifact_link_cutover_marker_path(role.root)
        if path.is_symlink():
            raise RuntimeError(f"artifact-link cutover marker is a symlink: {path}")
        if path.is_file() and path.read_bytes() == payload:
            continue
        if path.is_file():
            existing = read_artifact_link_cutover_marker(
                role.root,
                expected_project_key=plan.project_key,
            )
            if existing is not None:
                _assert_same_import(existing, marker)
        atomic_write_bytes(path, payload)
        changed.append(path)
        changed_by_root.setdefault(role.root, []).append(path)
    if changed:
        result = commit_artifact_link_indexes(
            (),
            store=None,
            project_key=plan.project_key,
            repo_roots=plan.sidecar_roots,
            extra_paths_by_root=changed_by_root,
            mutation_origin="machine",
            push_after_commit=push_after_commit,
            verify_publication=True,
            message="chore(artifact-links): persist link event store marker",
        )
        if result.publication_error:
            raise RuntimeError(result.publication_error)
    return tuple(changed)


def _assert_marker_state_allows_plan(
    store: ArtifactLinkStore,
    *,
    roles: Sequence[_ArtifactLinkImportRole],
) -> None:
    inspection = inspect_artifact_link_cutover_markers(
        store.sidecar_roots,
        project_key=store.project_key,
    )
    if inspection.marker is None:
        return
    marker_roles = tuple(role.marker_role() for role in roles)
    expected_payload = build_artifact_link_cutover_marker_payload(
        state=inspection.marker.state,
        project_key=store.project_key,
        event_store_schema_version=1,
        event_store_minimum_event_schema_version=int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        import_identity=inspection.marker.import_identity,
        roles=marker_roles,
        baseline_event=inspection.marker.baseline_event,
    )
    expected_marker_bytes = artifact_link_cutover_marker_bytes(expected_payload)
    if expected_marker_bytes != inspection.marker.canonical_bytes:
        raise RuntimeError(
            "artifact-link cutover marker no longer matches sidecar HEADs"
        )


def _assert_same_import(
    existing: ArtifactLinkCutoverMarker,
    expected: ArtifactLinkCutoverMarker,
) -> None:
    if existing.import_identity != expected.import_identity:
        raise RuntimeError("artifact-link cutover marker import identity mismatch")
    if existing.baseline_event != expected.baseline_event:
        raise RuntimeError("artifact-link cutover marker baseline event mismatch")
    if existing.roles != expected.roles:
        raise RuntimeError("artifact-link cutover marker source-head mismatch")


def _assert_baseline_reducer_parity(
    event: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    from sase.sdd.artifact_link_event_publisher import rows_from_events

    reduced = rows_from_events((event,))
    if _sorted_rows(reduced) != _sorted_rows(rows):
        raise RuntimeError("baseline import event does not reduce to legacy rows")


def _assert_baseline_durable(
    store: ArtifactLinkStore,
    plan: _ArtifactLinkIndexImportPlan,
) -> None:
    snapshot = store.artifact_link_event_snapshot(include_pending=False, strict=True)
    durable_identities = {
        artifact_link_row_identity(row) for row in snapshot.durable_rows
    }
    missing = [
        " ".join(artifact_link_row_identity(row))
        for row in plan.rows
        if artifact_link_row_identity(row) not in durable_identities
    ]
    if missing:
        raise RuntimeError(
            "baseline import event did not become durable for rows: "
            + ", ".join(missing[:4])
        )


def _logical_row_signature(row: Mapping[str, Any]) -> bytes:
    data = dict(validate_artifact_link_row(row))
    identity = artifact_link_row_identity(data)
    if identity[:1] == ("undirected",):
        left, right = sorted(
            (str(data.get("source_ref") or ""), str(data.get("target_ref") or ""))
        )
        data["source_ref"] = left
        data["target_ref"] = right
    return canonical_json_bytes(data)


def _sorted_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        unique_rows(validate_artifact_link_row(row) for row in rows),
        key=lambda row: canonical_json_bytes(row),
    )


def _git_output(
    root: Path,
    *args: str,
    check: bool = True,
) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git failed"
        raise RuntimeError(f"git {' '.join(args)} failed for {root}: {message}")
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


__all__ = [
    "ArtifactLinkIndexImportReport",
    "artifact_link_legacy_links_tree_identity",
    "import_artifact_link_indexes",
]
