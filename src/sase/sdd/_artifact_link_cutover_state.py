"""Artifact-link legacy-index cutover marker adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
        return _artifact_link_cutover_marker_bytes(self.payload)

    def with_state(
        self, state: Literal["fenced", "imported"]
    ) -> ArtifactLinkCutoverMarker:
        payload = {**self.payload, "state": state}
        return parse_artifact_link_cutover_marker_payload(payload)


@dataclass(frozen=True, slots=True)
class _ArtifactLinkCutoverInspection:
    """Cutover marker state across all document sidecar roots."""

    state: Literal["none", "fenced", "imported", "incomplete"]
    marker: ArtifactLinkCutoverMarker | None = None
    incomplete_roles: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def fenced(self) -> bool:
        return self.state in {"fenced", "imported", "incomplete"}

    @property
    def imported(self) -> bool:
        return self.state == "imported"


def role_for_artifact_link_kind(kind: str) -> str:
    """Return the SDD sidecar role for one artifact-ref kind."""

    return PLANS_ROLE if kind == PLAN_KIND else kind


def artifact_link_cutover_marker_path(root: Path) -> Path:
    """Return the cutover marker path under one document sidecar root."""

    return (
        root.expanduser().resolve(strict=False)
        / ARTIFACT_LINK_CUTOVER_MARKER_RELATIVE_PATH
    )


def _artifact_link_cutover_marker_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return canonical marker bytes from Rust policy."""

    return str(
        require_rust_binding("artifact_link_cutover_marker_canonical_json")(
            dict(payload)
        )
    ).encode("utf-8")


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
    """Build and validate a canonicalizable marker payload."""

    return dict(
        require_rust_binding("artifact_link_cutover_marker_build")(
            state,
            project_key,
            {
                "minimum_event_schema_version": int(
                    event_store_minimum_event_schema_version
                ),
                "schema_version": int(event_store_schema_version),
            },
            import_identity.to_json_dict(),
            [role.to_json_dict() for role in roles],
            baseline_event.to_json_dict(),
        )
    )


def artifact_link_cutover_attestation(
    marker: ArtifactLinkCutoverMarker,
) -> str:
    """Return the operator attestation token for one cutover marker."""

    return str(
        require_rust_binding("artifact_link_cutover_attestation")(marker.payload)
    )


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
        payload_text = payload_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"artifact-link cutover marker is not UTF-8: {path}"
        ) from exc
    marker = _marker_from_payload(
        require_rust_binding("artifact_link_cutover_marker_parse")(payload_text)
    )
    if payload_bytes != marker.canonical_bytes:
        raise RuntimeError(
            f"artifact-link cutover marker is not canonical JSON: {path}"
        )
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

    canonical = str(
        require_rust_binding("artifact_link_cutover_marker_canonical_json")(
            dict(payload)
        )
    )
    return _marker_from_payload(
        require_rust_binding("artifact_link_cutover_marker_parse")(canonical)
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
    observations: list[dict[str, Any]] = []
    for role, root in sorted(roots_by_role.items()):
        marker = read_artifact_link_cutover_marker(
            root,
            expected_project_key=project_key,
        )
        observations.append(
            {"marker": None if marker is None else marker.payload, "role": role}
        )
    state = dict(require_rust_binding("artifact_link_cutover_read_state")(observations))
    marker_payload = state.get("marker")
    marker = (
        None
        if not isinstance(marker_payload, Mapping)
        else _marker_from_payload(marker_payload)
    )
    return _ArtifactLinkCutoverInspection(
        state=str(state.get("state") or "none"),  # type: ignore[arg-type]
        marker=marker,
        incomplete_roles=tuple(str(role) for role in state.get("incomplete_roles", ())),
        diagnostics=tuple(str(item) for item in state.get("diagnostics", ())),
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

    inspection = inspect_artifact_link_cutover_markers(
        sidecar_roots,
        project_key=project_key,
    )
    if inspection.state == "incomplete":
        raise RuntimeError(_incomplete_cutover_message(inspection))
    return inspection.imported


def _marker_from_payload(payload: Mapping[str, Any]) -> ArtifactLinkCutoverMarker:
    data = dict(payload)
    import_payload = data.get("import")
    baseline_payload = data.get("baseline_event")
    if not isinstance(import_payload, Mapping) or not isinstance(
        baseline_payload, Mapping
    ):
        raise RuntimeError("sase_core_rs returned malformed cutover marker")
    roles = data.get("roles")
    if not isinstance(roles, list):
        raise RuntimeError("sase_core_rs returned malformed cutover marker roles")
    return ArtifactLinkCutoverMarker(
        schema_version=int(data["schema_version"]),
        state=str(data["state"]),  # type: ignore[arg-type]
        project_key=str(data["project_key"]),
        event_store={
            str(key): int(value) for key, value in dict(data["event_store"]).items()
        },
        import_identity=ArtifactLinkCutoverImportIdentity(
            import_id=str(import_payload["import_id"]),
            operation_id=str(import_payload["operation_id"]),
            source_head=str(import_payload["source_head"]),
            created_at=str(import_payload["created_at"]),
        ),
        roles=tuple(
            ArtifactLinkCutoverRole(
                role=str(role["role"]),
                kind=str(role["kind"]),
                head=str(role["head"]),
                links_tree=str(role["links_tree"]),
                remote_url=str(role["remote_url"]),
            )
            for role in roles
            if isinstance(role, Mapping)
        ),
        baseline_event=ArtifactLinkBaselineEventIdentity(
            digest=str(baseline_payload["digest"]),
            path=str(baseline_payload["path"]),
        ),
        payload=data,
    )


def _roots_by_role(sidecar_roots: Mapping[str, Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for kind, root in sidecar_roots.items():
        role = role_for_artifact_link_kind(str(kind))
        resolved = root.expanduser().resolve(strict=False)
        result.setdefault(role, resolved)
    return result


def _incomplete_cutover_message(inspection: _ArtifactLinkCutoverInspection) -> str:
    roles = ", ".join(inspection.incomplete_roles) or "unknown"
    marker = inspection.marker
    if marker is None:
        command = "sase artifact link import-indexes"
    else:
        command = (
            "sase artifact link import-indexes --apply "
            f"{artifact_link_cutover_attestation(marker)}"
        )
    details = "; ".join(inspection.diagnostics) or "cutover is incomplete"
    return (
        "artifact-link cutover is incomplete; resume with "
        f"`{command}`. Affected roles: {roles}. {details}"
    )


__all__ = [
    "ARTIFACT_LINK_CUTOVER_MARKER_RELATIVE_PATH",
    "ARTIFACT_LINK_CUTOVER_MARKER_SCHEMA_VERSION",
    "ArtifactLinkBaselineEventIdentity",
    "ArtifactLinkCutoverImportIdentity",
    "ArtifactLinkCutoverMarker",
    "ArtifactLinkCutoverRole",
    "artifact_link_cutover_attestation",
    "artifact_link_cutover_marker_path",
    "artifact_link_indexes_imported",
    "build_artifact_link_cutover_marker_payload",
    "legacy_artifact_link_writes_fenced",
    "parse_artifact_link_cutover_marker_payload",
    "read_artifact_link_cutover_marker",
    "role_for_artifact_link_kind",
    "inspect_artifact_link_cutover_markers",
]
