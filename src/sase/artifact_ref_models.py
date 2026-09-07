"""Wire models for kind-tagged artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from sase.core.time import get_timezone, local_now


ARTIFACT_REF_WIRE_SCHEMA_VERSION = 5
ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION = 2
ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION = 1
ARTIFACT_REF_DOCUMENT_SCAN_WIRE_SCHEMA_VERSION = 1
ARTIFACT_REF_TARGET_RESOLUTION_WIRE_SCHEMA_VERSION = 1

ArtifactRefKindType = Literal[
    "commit",
    "chat",
    "bug",
    "file",
    "bead",
    "agent",
    "stitch",
    "patch",
    "document",
]
ArtifactRefPayloadType = ArtifactRefKindType
ArtifactRefFragmentType = Literal["lines", "page", "time"]
ArtifactRefResolutionStatus = Literal[
    "exact",
    "drifted",
    "vcs_backed",
    "ambiguous",
    "missing",
    "unknown_kind",
    "unknown_repo",
    "unknown_project",
    "filtered",
    "denied",
]
ArtifactRefDocumentTargetKind = Literal["artifact_ref", "url", "file_path"]
ArtifactRefTargetFailureCategory = Literal[
    "missing_checkout",
    "unavailable_revision",
    "ambiguous",
    "denied_filtered",
    "temporary_error",
    "proven_missing",
]


@dataclass(frozen=True, slots=True)
class ArtifactRefPayload:
    """One kind-specific artifact-reference payload."""

    type: ArtifactRefPayloadType
    path: str | None = None
    repo: str | None = None
    sha: str | None = None
    project: str | None = None
    number: int | None = None
    source: str | None = None
    digest: str | None = None
    id: str | None = None
    name: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefPayload:
        payload_type = str(raw["type"])
        if payload_type not in {
            "commit",
            "chat",
            "bug",
            "file",
            "file_path",
            "bead",
            "agent",
            "stitch",
            "patch",
            "document",
        }:
            raise RuntimeError(
                "sase_core_rs returned an unknown artifact-reference payload "
                f"type: {payload_type}"
            )
        return cls(
            type=cast(ArtifactRefPayloadType, payload_type),
            path=optional_str(raw.get("path")),
            repo=optional_str(raw.get("repo")),
            sha=optional_str(raw.get("sha")),
            project=optional_str(raw.get("project")),
            number=_optional_int(raw.get("number")),
            source=optional_str(raw.get("source")),
            digest=optional_str(raw.get("digest")),
            id=optional_str(raw.get("id")),
            name=optional_str(raw.get("name")),
        )

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {"type": self.type}
        for name in (
            "path",
            "repo",
            "sha",
            "project",
            "number",
            "source",
            "digest",
            "id",
            "name",
        ):
            value = getattr(self, name)
            if value is not None:
                raw[name] = value
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefFragment:
    """One optional artifact-reference fragment anchor."""

    type: ArtifactRefFragmentType
    start: int | None = None
    end: int | None = None
    page: int | None = None
    seconds: int | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefFragment:
        fragment_type = str(raw["type"])
        if fragment_type not in {"lines", "page", "time"}:
            raise RuntimeError(
                "sase_core_rs returned an unknown artifact-reference fragment "
                f"type: {fragment_type}"
            )
        return cls(
            type=cast(ArtifactRefFragmentType, fragment_type),
            start=_optional_int(raw.get("start")),
            end=_optional_int(raw.get("end")),
            page=_optional_int(raw.get("page")),
            seconds=_optional_int(raw.get("seconds")),
        )

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {"type": self.type}
        for name in ("start", "end", "page", "seconds"):
            value = getattr(self, name)
            if value is not None:
                raw[name] = value
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """A parsed canonical artifact reference."""

    schema_version: int
    kind: str
    kind_type: ArtifactRefKindType
    payload: ArtifactRefPayload
    fragment: ArtifactRefFragment | None
    rendered: str

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRef:
        check_record_schema(raw, record="artifact-reference parse")
        raw_kind = cast(Mapping[str, Any], raw["kind"])
        kind_type = str(raw_kind["type"])
        if kind_type not in {
            "commit",
            "chat",
            "bug",
            "file",
            "bead",
            "agent",
            "stitch",
            "patch",
            "document",
        }:
            raise RuntimeError(
                "sase_core_rs returned an unknown artifact-reference kind "
                f"type: {kind_type}"
            )
        kind = str(raw_kind["role"]) if kind_type == "document" else kind_type
        raw_fragment = raw.get("fragment")
        return cls(
            schema_version=int(raw["schema_version"]),
            kind=kind,
            kind_type=cast(ArtifactRefKindType, kind_type),
            payload=ArtifactRefPayload.from_wire(
                cast(Mapping[str, Any], raw["payload"])
            ),
            fragment=(
                None
                if raw_fragment is None
                else ArtifactRefFragment.from_wire(
                    cast(Mapping[str, Any], raw_fragment)
                )
            ),
            rendered=str(raw["rendered"]),
        )

    def to_wire(self) -> dict[str, object]:
        kind: dict[str, object] = {"type": self.kind_type}
        if self.kind_type == "document":
            kind["role"] = self.kind
        return {
            "schema_version": self.schema_version,
            "kind": kind,
            "payload": self.payload.to_wire(),
            "fragment": (None if self.fragment is None else self.fragment.to_wire()),
            "rendered": self.rendered,
        }


ParsedArtifactRef = ArtifactRef


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentRoot:
    kind: str
    root: Path
    path_globs: tuple[str, ...] | None = None

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {"kind": self.kind, "root": str(self.root)}
        if self.path_globs is not None:
            raw["path_globs"] = list(self.path_globs)
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefFileRoot:
    name: str
    root: Path
    path_globs: tuple[str, ...] | None = None

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {"name": self.name, "path": str(self.root)}
        if self.path_globs is not None:
            raw["path_globs"] = list(self.path_globs)
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefRepository:
    name: str
    aliases: tuple[str, ...] = ()
    shas: tuple[str, ...] = ()
    checkout_path: Path | None = None
    checkout_paths: tuple[Path, ...] = ()
    kind: str = ""

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "shas": list(self.shas),
            "checkout_paths": [str(path) for path in self.checkout_paths],
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefProject:
    name: str
    key: str
    aliases: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "key": self.key,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefBeadStore:
    project: str
    prefix: str
    root: Path

    def to_wire(self) -> dict[str, str]:
        return {
            "project": self.project,
            "prefix": self.prefix,
            "root": str(self.root),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefAgentRoot:
    project: str
    root: Path

    def to_wire(self) -> dict[str, str]:
        return {"project": self.project, "root": str(self.root)}


@dataclass(frozen=True, slots=True)
class ArtifactRefAgentOwner:
    username: str
    machine_name: str

    def to_wire(self) -> dict[str, str]:
        return {
            "username": self.username,
            "machine_name": self.machine_name,
        }


ArtifactEntryOrigin = Literal["prompt_ref", "agent_artifact", "both"]


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    """A normalized artifact-entry, mirroring ``ArtifactEntryWire``.

    Constructed by the Python builtin-entry resolvers (stitch/patch/bead/agent);
    always pass a freshly built entry through :func:`artifact_ref_entry_validate`
    before use.
    """

    stable_id: str
    ref_kind: str
    canonical_argument: str
    display_label: str
    origin: ArtifactEntryOrigin
    project_display_name: str | None = None
    repository: str | None = None
    repo_relative_path: str | None = None
    captured_revision: str | None = None
    captured_digest: str | None = None
    logical_path: str | None = None
    properties: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def to_wire(self) -> dict[str, object]:
        # Lazy import: artifact_ref_operations imports ArtifactRef from this module.
        from sase.artifact_ref_operations import artifact_ref_entry_wire_schema_version

        raw: dict[str, object] = {
            "schema_version": artifact_ref_entry_wire_schema_version(),
            "stable_id": self.stable_id,
            "ref_kind": self.ref_kind,
            "canonical_argument": self.canonical_argument,
            "display_label": self.display_label,
            "properties": dict(self.properties),
            "origin": self.origin,
        }
        for name in (
            "project_display_name",
            "repository",
            "repo_relative_path",
            "captured_revision",
            "captured_digest",
            "logical_path",
        ):
            value = getattr(self, name)
            if value is not None:
                raw[name] = value
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentExpansion:
    """One document kind's Python-owned expansion-format policy.

    Carried on :class:`ArtifactRefContext` for Python-side rendering only;
    never sent across the Rust wire (see ``ArtifactRefContext.to_wire``).
    """

    kind: str
    role: str
    expansion_format: str
    is_pointer: bool


def _utc_offset_seconds() -> int:
    """Return the configured timezone's current UTC offset in whole seconds."""

    offset = get_timezone().utcoffset(local_now())
    return 0 if offset is None else int(offset.total_seconds())


@dataclass(frozen=True, slots=True)
class ArtifactRefContext:
    """Caller-supplied local namespaces used by the Rust resolver."""

    document_roots: tuple[ArtifactRefDocumentRoot, ...]
    chats_root: Path
    artifact_index_path: Path
    repositories: tuple[ArtifactRefRepository, ...]
    projects: tuple[ArtifactRefProject, ...]
    file_roots: tuple[ArtifactRefFileRoot, ...] = ()
    bead_stores: tuple[ArtifactRefBeadStore, ...] = ()
    agent_roots: tuple[ArtifactRefAgentRoot, ...] = ()
    agent_owner: ArtifactRefAgentOwner | None = None
    home_dir: Path | None = None
    file_capture_max_bytes: int | None = None
    selected_project: str | None = None
    document_expansions: tuple[ArtifactRefDocumentExpansion, ...] = ()

    @property
    def known_kinds(self) -> tuple[str, ...]:
        # Lazy import: artifact_ref_kinds imports ArtifactRef from this module.
        from sase.artifact_ref_kinds import parsable_artifact_ref_kinds

        return tuple(
            dict.fromkeys(
                (
                    *parsable_artifact_ref_kinds(),
                    *(entry.kind for entry in self.document_roots),
                )
            )
        )

    def document_expansion_for(self, kind: str) -> ArtifactRefDocumentExpansion | None:
        return next(
            (entry for entry in self.document_expansions if entry.kind == kind),
            None,
        )

    def document_is_pointer(self, kind: str) -> bool:
        """Return whether *kind* expands as a pointer rather than a local path.

        Unconfigured document kinds use the default sidecar pointer format, so
        a missing expansion policy is a pointer rather than a path-bound
        fallback.
        """

        expansion = self.document_expansion_for(kind)
        if expansion is None:
            return True
        return expansion.is_pointer

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": ARTIFACT_REF_CONTEXT_WIRE_SCHEMA_VERSION,
            "document_roots": [document.to_wire() for document in self.document_roots],
            "file_roots": [root.to_wire() for root in self.file_roots],
            "chats_root": str(self.chats_root),
            "artifact_index_path": str(self.artifact_index_path),
            "repositories": [repository.to_wire() for repository in self.repositories],
            "projects": [project.to_wire() for project in self.projects],
            "bead_stores": [store.to_wire() for store in self.bead_stores],
            "agent_roots": [root.to_wire() for root in self.agent_roots],
            "agent_owner": (
                None if self.agent_owner is None else self.agent_owner.to_wire()
            ),
            "home_dir": None if self.home_dir is None else str(self.home_dir),
            "file_capture_max_bytes": self.file_capture_max_bytes,
            "utc_offset_seconds": _utc_offset_seconds(),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefResolution:
    schema_version: int
    status: ArtifactRefResolutionStatus
    rendered: str
    locator: str | None
    resolved_path: Path | None
    candidates: tuple[str, ...]
    diagnostic: str | None = None

    @property
    def best_path(self) -> Path | None:
        if self.resolved_path is not None:
            return self.resolved_path
        if not self.candidates or self.status not in {"ambiguous", "missing"}:
            return None
        return Path(self.candidates[0])


@dataclass(frozen=True, slots=True)
class ArtifactRefPathFilterResult:
    """Result from the Rust-owned artifact-reference path filter."""

    schema_version: int
    kind: str
    allowed: tuple[str, ...]
    filtered: tuple[str, ...]

    @classmethod
    def from_wire(
        cls,
        raw: Mapping[str, Any],
        *,
        record: str = "artifact-reference path filter",
    ) -> ArtifactRefPathFilterResult:
        version = int(raw["schema_version"])
        if version != ARTIFACT_REF_PATH_FILTER_WIRE_SCHEMA_VERSION:
            raise RuntimeError(
                f"sase_core_rs returned an unsupported {record} wire: {version}"
            )
        return cls(
            schema_version=version,
            kind=str(raw["kind"]),
            allowed=tuple(str(item) for item in raw.get("allowed", ())),
            filtered=tuple(str(item) for item in raw.get("filtered", ())),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRefSpan:
    start: int
    end: int

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefSpan:
        return cls(start=int(raw["start"]), end=int(raw["end"]))


@dataclass(frozen=True, slots=True)
class ArtifactRefPromptCandidate:
    schema_version: int
    text: str
    reference: str
    kind: str
    well_formed: bool
    candidate_span: ArtifactRefSpan
    sigil_span: ArtifactRefSpan
    kind_span: ArtifactRefSpan
    separator_span: ArtifactRefSpan
    payload_span: ArtifactRefSpan
    fragment_span: ArtifactRefSpan | None
    quoted: bool = False

    @classmethod
    def from_wire(
        cls,
        raw: Mapping[str, Any],
    ) -> ArtifactRefPromptCandidate:
        check_record_schema(raw, record="artifact-reference scan")
        raw_fragment = raw.get("fragment_span")
        return cls(
            schema_version=int(raw["schema_version"]),
            text=str(raw["text"]),
            reference=str(raw["reference"]),
            kind=str(raw["kind"]),
            well_formed=bool(raw["well_formed"]),
            candidate_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["candidate_span"])
            ),
            sigil_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["sigil_span"])
            ),
            kind_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["kind_span"])
            ),
            separator_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["separator_span"])
            ),
            payload_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["payload_span"])
            ),
            fragment_span=(
                None
                if raw_fragment is None
                else ArtifactRefSpan.from_wire(cast(Mapping[str, Any], raw_fragment))
            ),
            quoted=bool(raw.get("quoted", False)),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentTarget:
    """One document-scanner target with separate visible text and destination."""

    schema_version: int
    target_kind: ArtifactRefDocumentTargetKind
    text: str
    target: str
    well_formed: bool
    source_span: ArtifactRefSpan
    candidate_span: ArtifactRefSpan
    target_span: ArtifactRefSpan
    label_span: ArtifactRefSpan | None
    destination_span: ArtifactRefSpan | None
    reference_label: str | None = None
    markdown_destination: str | None = None
    hosted_destination: str | None = None
    artifact_reference: str | None = None
    quoted: bool = False

    @classmethod
    def from_wire(
        cls,
        raw: Mapping[str, Any],
    ) -> ArtifactRefDocumentTarget:
        _check_document_scan_record_schema(
            raw, record="artifact-reference document target"
        )
        target_kind = str(raw["target_kind"])
        if target_kind not in {"artifact_ref", "url", "file_path"}:
            raise RuntimeError(
                "sase_core_rs returned an unknown artifact-reference document "
                f"target kind: {target_kind}"
            )
        raw_label_span = raw.get("label_span")
        raw_destination_span = raw.get("destination_span")
        return cls(
            schema_version=int(raw["schema_version"]),
            target_kind=cast(ArtifactRefDocumentTargetKind, target_kind),
            text=str(raw["text"]),
            target=str(raw["target"]),
            well_formed=bool(raw["well_formed"]),
            source_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["source_span"])
            ),
            candidate_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["candidate_span"])
            ),
            target_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["target_span"])
            ),
            label_span=(
                None
                if raw_label_span is None
                else ArtifactRefSpan.from_wire(cast(Mapping[str, Any], raw_label_span))
            ),
            destination_span=(
                None
                if raw_destination_span is None
                else ArtifactRefSpan.from_wire(
                    cast(Mapping[str, Any], raw_destination_span)
                )
            ),
            reference_label=optional_str(raw.get("reference_label")),
            markdown_destination=optional_str(raw.get("markdown_destination")),
            hosted_destination=optional_str(raw.get("hosted_destination")),
            artifact_reference=optional_str(raw.get("artifact_reference")),
            quoted=bool(raw.get("quoted", False)),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentScan:
    schema_version: int
    links: tuple[ArtifactRefDocumentTarget, ...]
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefDocumentScan:
        _check_document_scan_record_schema(
            raw, record="artifact-reference document scan"
        )
        return cls(
            schema_version=int(raw["schema_version"]),
            links=tuple(
                ArtifactRefDocumentTarget.from_wire(cast(Mapping[str, Any], item))
                for item in raw.get("links", ())
            ),
            diagnostics=tuple(str(item) for item in raw.get("diagnostics", ())),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentOwner:
    """Provenance for a scanned document link's own source.

    Lets an unqualified source path resolve in the repository that actually
    owns the document naming it, rather than the viewer's cwd. Every field is
    optional: absent provenance falls back to searching every repository in
    the caller's resolution context.
    """

    source_reference: str | None = None
    project_key: str | None = None
    repository: str | None = None
    revision: str | None = None
    source_directory: str | None = None
    checkout_candidates: tuple[Path, ...] = ()

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {
            "checkout_candidates": [str(path) for path in self.checkout_candidates],
        }
        for name in (
            "source_reference",
            "project_key",
            "repository",
            "revision",
            "source_directory",
        ):
            value = getattr(self, name)
            if value is not None:
                raw[name] = value
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefTargetCandidate:
    """One inspected or selected candidate, kept as resolution evidence."""

    path: str
    evidence: str
    repository: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefTargetCandidate:
        return cls(
            path=str(raw["path"]),
            evidence=str(raw["evidence"]),
            repository=optional_str(raw.get("repository")),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRefTargetResolution:
    """The outcome of resolving one document-owned source-path target."""

    schema_version: int
    status: str
    resolved_path: Path | None
    repository: str | None
    revision: str | None
    candidates: tuple[ArtifactRefTargetCandidate, ...]
    failure_category: ArtifactRefTargetFailureCategory | None
    retryable: bool
    diagnostic: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefTargetResolution:
        version = int(raw["schema_version"])
        if version != ARTIFACT_REF_TARGET_RESOLUTION_WIRE_SCHEMA_VERSION:
            raise RuntimeError(
                "sase_core_rs returned an unsupported artifact-reference "
                f"target resolution wire: {version}"
            )
        resolved_path = raw.get("resolved_path")
        failure_category = raw.get("failure_category")
        return cls(
            schema_version=version,
            status=str(raw["status"]),
            resolved_path=None if resolved_path is None else Path(str(resolved_path)),
            repository=optional_str(raw.get("repository")),
            revision=optional_str(raw.get("revision")),
            candidates=tuple(
                ArtifactRefTargetCandidate.from_wire(cast(Mapping[str, Any], item))
                for item in raw.get("candidates", ())
            ),
            failure_category=(
                None
                if failure_category is None
                else cast(ArtifactRefTargetFailureCategory, str(failure_category))
            ),
            retryable=bool(raw["retryable"]),
            diagnostic=optional_str(raw.get("diagnostic")),
        )


def check_record_schema(
    raw: Mapping[str, Any],
    *,
    record: str,
) -> None:
    version = int(raw["schema_version"])
    if version != ARTIFACT_REF_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs returned an unsupported {record} wire: {version}"
        )


def _check_document_scan_record_schema(
    raw: Mapping[str, Any],
    *,
    record: str,
) -> None:
    version = int(raw["schema_version"])
    if version != ARTIFACT_REF_DOCUMENT_SCAN_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs returned an unsupported {record} wire: {version}"
        )


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: object) -> int | None:
    return None if value is None else int(cast(Any, value))
