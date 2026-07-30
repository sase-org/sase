"""Wire models for kind-tagged artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast


ARTIFACT_REF_WIRE_SCHEMA_VERSION = 3
BUILTIN_ARTIFACT_REF_KINDS = ("commit", "chat", "bug", "file", "bead", "agent")

ArtifactRefKindType = Literal[
    "commit",
    "chat",
    "bug",
    "file",
    "bead",
    "agent",
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
            "bead",
            "agent",
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

    def to_wire(self) -> dict[str, str]:
        return {"kind": self.kind, "root": str(self.root)}


@dataclass(frozen=True, slots=True)
class ArtifactRefRepository:
    name: str
    aliases: tuple[str, ...] = ()
    shas: tuple[str, ...] = ()
    checkout_path: Path | None = None
    checkout_paths: tuple[Path, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "shas": list(self.shas),
            "checkout_paths": [str(path) for path in self.checkout_paths],
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


@dataclass(frozen=True, slots=True)
class ArtifactRefContext:
    """Caller-supplied local namespaces used by the Rust resolver."""

    document_roots: tuple[ArtifactRefDocumentRoot, ...]
    chats_root: Path
    artifact_index_path: Path
    repositories: tuple[ArtifactRefRepository, ...]
    projects: tuple[ArtifactRefProject, ...]
    bead_stores: tuple[ArtifactRefBeadStore, ...] = ()
    agent_roots: tuple[ArtifactRefAgentRoot, ...] = ()
    agent_owner: ArtifactRefAgentOwner | None = None

    @property
    def known_kinds(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *BUILTIN_ARTIFACT_REF_KINDS,
                    *(entry.kind for entry in self.document_roots),
                )
            )
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "document_roots": [document.to_wire() for document in self.document_roots],
            "chats_root": str(self.chats_root),
            "artifact_index_path": str(self.artifact_index_path),
            "repositories": [repository.to_wire() for repository in self.repositories],
            "projects": [project.to_wire() for project in self.projects],
            "bead_stores": [store.to_wire() for store in self.bead_stores],
            "agent_roots": [root.to_wire() for root in self.agent_roots],
            "agent_owner": (
                None if self.agent_owner is None else self.agent_owner.to_wire()
            ),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefResolution:
    schema_version: int
    status: ArtifactRefResolutionStatus
    rendered: str
    locator: str | None
    resolved_path: Path | None
    candidates: tuple[str, ...]

    @property
    def best_path(self) -> Path | None:
        if self.resolved_path is not None:
            return self.resolved_path
        if not self.candidates or self.status not in {"ambiguous", "missing"}:
            return None
        return Path(self.candidates[0])


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


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: object) -> int | None:
    return None if value is None else int(cast(Any, value))
