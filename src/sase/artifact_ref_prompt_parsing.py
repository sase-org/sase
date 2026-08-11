"""Prompt scanning helpers for launch-prompt artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.artifact_ref_models import ArtifactRefSpan


@dataclass(frozen=True, slots=True)
class ArtifactRefFailure:
    reference: str
    status: str
    detail: str | None = None


def byte_to_character_offsets(text: str) -> dict[int, int]:
    offsets = {0: 0}
    byte_offset = 0
    for character_offset, character in enumerate(text, start=1):
        byte_offset += len(character.encode("utf-8"))
        offsets[byte_offset] = character_offset
    return offsets


def character_span(
    span: ArtifactRefSpan,
    *,
    byte_to_char: Mapping[int, int],
) -> tuple[int, int]:
    try:
        return byte_to_char[span.start], byte_to_char[span.end]
    except KeyError as exc:
        raise RuntimeError(
            "sase_core_rs returned an artifact-reference span outside UTF-8 "
            "character boundaries"
        ) from exc


def overlaps_any(
    start: int,
    end: int,
    ranges: list[tuple[int, int]],
) -> bool:
    return any(
        start < range_end and end > range_start for range_start, range_end in ranges
    )


def print_artifact_ref_failures(failures: list[ArtifactRefFailure]) -> None:
    print("\n❌ ERROR: The following artifact reference(s) could not be resolved:")
    for failure in failures:
        detail = f": {failure.detail}" if failure.detail else ""
        print(f"  - {failure.reference} ({failure.status}{detail})")
    print("\n⚠️ Artifact reference validation failed. Terminating workflow.\n")
