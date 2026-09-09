"""Prompt and document scan models for artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from sase.artifact_ref_wire import (
    ArtifactRefDocumentTargetKind,
    check_document_scan_record_schema,
    check_record_schema,
    optional_str,
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
        check_document_scan_record_schema(
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
        check_document_scan_record_schema(
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


__all__ = [
    "ArtifactRefDocumentScan",
    "ArtifactRefDocumentTarget",
    "ArtifactRefPromptCandidate",
    "ArtifactRefSpan",
]
