"""Parsed canonical artifact-reference models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from sase.artifact_ref_wire import (
    ArtifactRefFragmentType,
    ArtifactRefKindType,
    ArtifactRefPayloadType,
    check_record_schema,
    optional_int,
    optional_str,
)


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
            number=optional_int(raw.get("number")),
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
            start=optional_int(raw.get("start")),
            end=optional_int(raw.get("end")),
            page=optional_int(raw.get("page")),
            seconds=optional_int(raw.get("seconds")),
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


__all__ = [
    "ArtifactRef",
    "ArtifactRefFragment",
    "ArtifactRefPayload",
    "ParsedArtifactRef",
]
