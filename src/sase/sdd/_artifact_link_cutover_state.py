"""Artifact-link legacy-index cutover marker contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from sase.agents_sync.io import canonical_json_bytes
from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_store_support import PLAN_KIND, PLANS_ROLE

ARTIFACT_LINK_CUTOVER_MARKER_RELATIVE_PATH = Path("link-events") / "STORE.json"
ARTIFACT_LINK_CUTOVER_MARKER_SCHEMA_VERSION = 1
ARTIFACT_LINK_CUTOVER_STATES = frozenset({"fenced", "imported"})


@dataclass(frozen=True, slots=True)
class ArtifactLinkCutoverRole:
    """Frozen source identity for one participating document sidecar."""

    role: str
    kind: str
    head: str
    links_tree: str
    remote_url: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "kind": self.kind,
            "links_tree": self.links_tree,
            "remote_url": self.remote_url,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class ArtifactLinkBaselineEventIdentity:
    """Content identity of the baseline import event object."""

    digest: str
    path: str

    def to_json_dict(self) -> dict[str, Any]:
        return {"digest": self.digest, "path": self.path}


@dataclass(frozen=True, slots=True)
class ArtifactLinkCutoverImportIdentity:
    """Deterministic identity for one legacy-index import."""

    import_id: str
    operation_id: str
    source_head: str
    created_at: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "import_id": self.import_id,
            "operation_id": self.operation_id,
            "source_head": self.source_head,
        }


@dataclass(frozen=True, slots=True)
class ArtifactLinkCutoverMarker:
    """Strictly parsed artifact-link cutover marker."""

    schema_version: int
    state: Literal["fenced", "imported"]
    project_key: str
    event_store: dict[str, int]
    import_identity: ArtifactLinkCutoverImportIdentity
    roles: tuple[ArtifactLinkCutoverRole, ...]
    baseline_event: ArtifactLinkBaselineEventIdentity
    payload: dict[str, Any]

    @property
    def import_id(self) -> str:
        return self.import_identity.import_id

    @property
    def operation_id(self) -> str:
        return self.import_identity.operation_id

    @property
    def canonical_bytes(self) -> bytes:
        return artifact_link_cutover_marker_bytes(self.payload)

    def with_state(
        self, state: Literal["fenced", "imported"]
    ) -> ArtifactLinkCutoverMarker:
        payload = {**self.payload, "state": state}
        return parse_artifact_link_cutover_marker_payload(payload)


@dataclass(frozen=True, slots=True)
class _ArtifactLinkCutoverInspection:
    """Cutover marker state across all document sidecar roots."""

    state: Literal["none", "fenced", "imported"]
    marker: ArtifactLinkCutoverMarker | None = None

    @property
    def fenced(self) -> bool:
        return self.state in {"fenced", "imported"}

    @property
    def imported(self) -> bool:
        return self.state == "imported"


def role_for_artifact_link_kind(kind: str) -> str:
    """Return the SDD sidecar role for one artifact-ref kind."""

    return PLANS_ROLE if kind == PLAN_KIND else kind


def _kind_for_artifact_link_role(role: str) -> str:
    """Return the artifact-ref kind stored by one document sidecar role."""

    return PLAN_KIND if role == PLANS_ROLE else role


def _artifact_link_cutover_marker_relpath() -> Path:
    """Return the repo-relative cutover marker path."""

    return ARTIFACT_LINK_CUTOVER_MARKER_RELATIVE_PATH


def artifact_link_cutover_marker_path(root: Path) -> Path:
    """Return the cutover marker path under one document sidecar root."""

    return (
        root.expanduser().resolve(strict=False)
        / _artifact_link_cutover_marker_relpath()
    )


def artifact_link_cutover_marker_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical marker bytes."""

    return canonical_json_bytes(dict(payload))


def build_artifact_link_cutover_marker_payload(
    *,
    state: Literal["fenced", "imported"],
    project_key: str,
    event_store_schema_version: int,
    event_store_minimum_event_schema_version: int,
    import_identity: ArtifactLinkCutoverImportIdentity,
    roles: Iterable[ArtifactLinkCutoverRole],
    baseline_event: ArtifactLinkBaselineEventIdentity,
) -> dict[str, Any]:
    """Build a canonicalizable marker payload."""

    return {
        "baseline_event": baseline_event.to_json_dict(),
        "event_store": {
            "minimum_event_schema_version": int(
                event_store_minimum_event_schema_version
            ),
            "schema_version": int(event_store_schema_version),
        },
        "import": import_identity.to_json_dict(),
        "project_key": project_key,
        "roles": [role.to_json_dict() for role in roles],
        "schema_version": ARTIFACT_LINK_CUTOVER_MARKER_SCHEMA_VERSION,
        "state": state,
    }


def read_artifact_link_cutover_marker(
    root: Path,
    *,
    expected_project_key: str | None = None,
    expected_roles: Iterable[str] | None = None,
) -> ArtifactLinkCutoverMarker | None:
    """Read and strictly validate one sidecar root's cutover marker."""

    path = artifact_link_cutover_marker_path(root)
    if not path.is_file():
        return None
    try:
        payload_bytes = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(
            f"could not read artifact-link cutover marker {path}: {exc}"
        ) from exc
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"malformed artifact-link cutover marker JSON: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"artifact-link cutover marker must be an object: {path}")
    expected_bytes = artifact_link_cutover_marker_bytes(payload)
    if payload_bytes != expected_bytes:
        raise RuntimeError(
            f"artifact-link cutover marker is not canonical JSON: {path}"
        )
    marker = parse_artifact_link_cutover_marker_payload(payload)
    if expected_project_key is not None and marker.project_key != expected_project_key:
        raise RuntimeError(
            "artifact-link cutover marker project mismatch: "
            f"{marker.project_key!r} != {expected_project_key!r}"
        )
    if expected_roles is not None:
        marker_roles = {role.role for role in marker.roles}
        expected_role_set = set(expected_roles)
        if marker_roles != expected_role_set:
            raise RuntimeError(
                "artifact-link cutover marker role mismatch: "
                f"{sorted(marker_roles)!r} != {sorted(expected_role_set)!r}"
            )
    return marker


def parse_artifact_link_cutover_marker_payload(
    payload: Mapping[str, Any],
) -> ArtifactLinkCutoverMarker:
    """Strictly parse a marker mapping."""

    data = dict(payload)
    _require_keys(
        data,
        {
            "baseline_event",
            "event_store",
            "import",
            "project_key",
            "roles",
            "schema_version",
            "state",
        },
        "artifact-link cutover marker",
    )
    schema_version = _require_int(data["schema_version"], "schema_version")
    if schema_version != ARTIFACT_LINK_CUTOVER_MARKER_SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported artifact-link cutover marker schema: {schema_version}"
        )
    state = _require_text(data["state"], "state")
    if state not in ARTIFACT_LINK_CUTOVER_STATES:
        raise RuntimeError(f"unsupported artifact-link cutover state: {state}")
    project_key = _require_text(data["project_key"], "project_key")
    event_store = _parse_event_store(data["event_store"])
    import_identity = _parse_import_identity(data["import"])
    roles = _parse_roles(data["roles"])
    baseline = _parse_baseline_event(data["baseline_event"])
    return ArtifactLinkCutoverMarker(
        schema_version=schema_version,
        state=state,  # type: ignore[arg-type]
        project_key=project_key,
        event_store=event_store,
        import_identity=import_identity,
        roles=roles,
        baseline_event=baseline,
        payload=data,
    )


def inspect_artifact_link_cutover_markers(
    sidecar_roots: Mapping[str, Path],
    *,
    project_key: str,
) -> _ArtifactLinkCutoverInspection:
    """Return the unified cutover state across document sidecar roots."""

    roots_by_role = _roots_by_role(sidecar_roots)
    if not roots_by_role:
        return _ArtifactLinkCutoverInspection(state="none")
    expected_roles = tuple(sorted(roots_by_role))
    markers: list[ArtifactLinkCutoverMarker] = []
    missing: list[str] = []
    for role, root in sorted(roots_by_role.items()):
        marker = read_artifact_link_cutover_marker(
            root,
            expected_project_key=project_key,
            expected_roles=expected_roles,
        )
        if marker is None:
            missing.append(role)
        else:
            markers.append(marker)
    if not markers:
        return _ArtifactLinkCutoverInspection(state="none")
    if missing:
        raise RuntimeError(
            "artifact-link cutover markers are partial; missing roles: "
            + ", ".join(missing)
        )
    canonical_payloads = {marker.canonical_bytes for marker in markers}
    if len(canonical_payloads) != 1:
        raise RuntimeError("artifact-link cutover markers are inconsistent")
    states = {marker.state for marker in markers}
    if len(states) != 1:
        raise RuntimeError("artifact-link cutover marker states are inconsistent")
    return _ArtifactLinkCutoverInspection(
        state=markers[0].state,
        marker=markers[0],
    )


def legacy_artifact_link_writes_fenced(
    sidecar_roots: Mapping[str, Path],
    *,
    project_key: str,
) -> bool:
    """Return whether direct legacy ``links/`` writes must be refused."""

    return inspect_artifact_link_cutover_markers(
        sidecar_roots,
        project_key=project_key,
    ).fenced


def artifact_link_indexes_imported(
    sidecar_roots: Mapping[str, Path],
    *,
    project_key: str,
) -> bool:
    """Return whether legacy ``links/`` indexes are no longer durable truth."""

    return inspect_artifact_link_cutover_markers(
        sidecar_roots,
        project_key=project_key,
    ).imported


def _roots_by_role(sidecar_roots: Mapping[str, Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for kind, root in sidecar_roots.items():
        role = role_for_artifact_link_kind(str(kind))
        resolved = root.expanduser().resolve(strict=False)
        result.setdefault(role, resolved)
    return result


def _parse_event_store(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise RuntimeError("artifact-link cutover marker event_store must be an object")
    data = dict(value)
    _require_keys(
        data,
        {"minimum_event_schema_version", "schema_version"},
        "artifact-link cutover marker event_store",
    )
    event_store = {
        "minimum_event_schema_version": _require_int(
            data["minimum_event_schema_version"],
            "event_store.minimum_event_schema_version",
        ),
        "schema_version": _require_int(
            data["schema_version"],
            "event_store.schema_version",
        ),
    }
    if event_store["schema_version"] != 1:
        raise RuntimeError(
            "unsupported artifact-link cutover event_store schema: "
            f"{event_store['schema_version']}"
        )
    current_event_schema = int(
        require_rust_binding("artifact_link_event_schema_version")()
    )
    if event_store["minimum_event_schema_version"] > current_event_schema:
        raise RuntimeError(
            "artifact-link cutover marker requires event schema "
            f"{event_store['minimum_event_schema_version']}; current is "
            f"{current_event_schema}"
        )
    return event_store


def _parse_import_identity(value: object) -> ArtifactLinkCutoverImportIdentity:
    if not isinstance(value, Mapping):
        raise RuntimeError("artifact-link cutover marker import must be an object")
    data = dict(value)
    _require_keys(
        data,
        {"created_at", "import_id", "operation_id", "source_head"},
        "artifact-link cutover marker import",
    )
    operation_id = _require_text(data["operation_id"], "import.operation_id")
    if len(operation_id) != 32 or any(
        char not in "0123456789abcdef" for char in operation_id
    ):
        raise RuntimeError("artifact-link cutover import operation_id must be 32 hex")
    return ArtifactLinkCutoverImportIdentity(
        import_id=_require_text(data["import_id"], "import.import_id"),
        operation_id=operation_id,
        source_head=_require_text(data["source_head"], "import.source_head"),
        created_at=_require_text(data["created_at"], "import.created_at"),
    )


def _parse_roles(value: object) -> tuple[ArtifactLinkCutoverRole, ...]:
    if not isinstance(value, list) or not value:
        raise RuntimeError(
            "artifact-link cutover marker roles must be a non-empty list"
        )
    roles: list[ArtifactLinkCutoverRole] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise RuntimeError("artifact-link cutover marker role must be an object")
        data = dict(item)
        _require_keys(
            data,
            {"head", "kind", "links_tree", "remote_url", "role"},
            "artifact-link cutover marker role",
        )
        role = _require_text(data["role"], "role.role")
        if role in seen:
            raise RuntimeError(f"duplicate artifact-link cutover role: {role}")
        seen.add(role)
        kind = _require_text(data["kind"], "role.kind")
        if _kind_for_artifact_link_role(role) != kind:
            raise RuntimeError(
                f"artifact-link cutover role {role!r} cannot store kind {kind!r}"
            )
        roles.append(
            ArtifactLinkCutoverRole(
                role=role,
                kind=kind,
                head=_require_text(data["head"], "role.head"),
                links_tree=_require_text(data["links_tree"], "role.links_tree"),
                remote_url=_require_text(data["remote_url"], "role.remote_url"),
            )
        )
    return tuple(sorted(roles, key=lambda role: role.role))


def _parse_baseline_event(value: object) -> ArtifactLinkBaselineEventIdentity:
    if not isinstance(value, Mapping):
        raise RuntimeError(
            "artifact-link cutover marker baseline_event must be an object"
        )
    data = dict(value)
    _require_keys(
        data,
        {"digest", "path"},
        "artifact-link cutover marker baseline_event",
    )
    digest = _require_text(data["digest"], "baseline_event.digest")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RuntimeError("artifact-link cutover baseline_event digest must be sha256")
    path = _require_text(data["path"], "baseline_event.path")
    if Path(path).is_absolute() or any(
        part in {"", ".", ".."} for part in Path(path).parts
    ):
        raise RuntimeError("artifact-link cutover baseline_event path must be relative")
    return ArtifactLinkBaselineEventIdentity(digest=digest, path=path)


def _require_keys(data: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(data)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        raise RuntimeError(f"{label} has invalid fields: {'; '.join(details)}")


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"artifact-link cutover marker {field} must be text")
    return value.strip()


def _require_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"artifact-link cutover marker {field} must be an integer")
    return value


__all__ = [
    "ARTIFACT_LINK_CUTOVER_MARKER_RELATIVE_PATH",
    "ARTIFACT_LINK_CUTOVER_MARKER_SCHEMA_VERSION",
    "ArtifactLinkBaselineEventIdentity",
    "ArtifactLinkCutoverImportIdentity",
    "ArtifactLinkCutoverMarker",
    "ArtifactLinkCutoverRole",
    "artifact_link_cutover_marker_bytes",
    "artifact_link_cutover_marker_path",
    "artifact_link_indexes_imported",
    "build_artifact_link_cutover_marker_payload",
    "legacy_artifact_link_writes_fenced",
    "parse_artifact_link_cutover_marker_payload",
    "read_artifact_link_cutover_marker",
    "role_for_artifact_link_kind",
    "inspect_artifact_link_cutover_markers",
]
