"""Prompt segment construction and normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from sase.core.continuation_wire import ContinuationPromptSegmentWire

from ._constants import _MAX_SEGMENTS
from ._storage import optional_int, source_ref, wire_reference_or_none
from .models import ContinuationSegmentCapture

if TYPE_CHECKING:
    from sase.xprompt._trace import ExpansionTrace


def local_authored_prompt_segment(text: str) -> ContinuationSegmentCapture:
    """Return a segment for the user's authored local request."""

    return ContinuationSegmentCapture(
        text=text,
        provenance="local_authored",
        source_ref="local:authored-request",
        source_label="authored local request",
    )


def local_materialized_prompt_segment(text: str) -> ContinuationSegmentCapture:
    """Return a segment for the exact local prompt sent to the provider."""

    return ContinuationSegmentCapture(
        text=text,
        provenance="local_materialized",
        source_ref="local:materialized-prompt",
        source_label="materialized local prompt",
    )


def xprompt_trace_segments(
    trace: ExpansionTrace,
    *,
    start_index: int = 0,
) -> tuple[ContinuationSegmentCapture, ...]:
    """Convert new xprompt expansion trace records into capture segments."""

    segments: list[ContinuationSegmentCapture] = []
    for index, record in enumerate(trace.records[start_index:], start=start_index):
        if not record.expanded_text:
            continue
        source_seed = f"{record.name}\0{record.source_path or ''}\0{index}"
        segments.append(
            ContinuationSegmentCapture(
                text=record.expanded_text,
                provenance="local_materialized",
                source_ref=source_ref("xprompt", record.name, source_seed),
                source_label=record.source_path,
            )
        )
    return tuple(segments)


def embedded_workflow_prompt_segment(
    name: str,
    text: str,
    *,
    source_path: str | None = None,
) -> ContinuationSegmentCapture:
    """Return a segment for rendered embedded workflow prompt_part text."""

    return ContinuationSegmentCapture(
        text=text,
        provenance="local_materialized",
        source_ref=source_ref("workflow", name, source_path or text),
        source_label=source_path,
    )


def complete_prompt_segments(
    *,
    authored_local_request: str,
    materialized_prompt: str,
    segments: Sequence[ContinuationSegmentCapture],
) -> list[ContinuationSegmentCapture]:
    normalized = list(segments)
    if not any(segment.provenance == "local_authored" for segment in normalized):
        normalized.insert(0, local_authored_prompt_segment(authored_local_request))
    if not any(
        segment.provenance == "local_materialized"
        and segment.text == materialized_prompt
        for segment in normalized
    ):
        normalized.append(local_materialized_prompt_segment(materialized_prompt))
    return normalized


def wire_segments_from_prepared(
    prepared_payload: Mapping[str, Any],
) -> list[ContinuationPromptSegmentWire]:
    raw_segments = prepared_payload.get("materialized_local_prompt_segments")
    if not isinstance(raw_segments, list):
        return []
    segments: list[ContinuationPromptSegmentWire] = []
    for raw in raw_segments[:_MAX_SEGMENTS]:
        if not isinstance(raw, Mapping):
            continue
        segment_id = raw.get("segment_id")
        provenance = raw.get("provenance")
        text_ref = raw.get("text_ref")
        text_sha = raw.get("text_sha256")
        utf8_bytes = optional_int(raw.get("utf8_bytes"))
        if not (
            isinstance(segment_id, str)
            and isinstance(provenance, str)
            and isinstance(text_ref, str)
            and isinstance(text_sha, str)
            and utf8_bytes is not None
        ):
            continue
        segment: ContinuationPromptSegmentWire = {
            "segment_id": segment_id,
            "provenance": provenance,  # type: ignore[typeddict-item]
            "text_ref": text_ref,
            "text_sha256": text_sha,
            "utf8_bytes": utf8_bytes,
        }
        source_ref = raw.get("source_ref")
        if isinstance(source_ref, str) and source_ref:
            segment["source_ref"] = source_ref
        segments.append(segment)
    return segments


__all__ = [
    "embedded_workflow_prompt_segment",
    "local_authored_prompt_segment",
    "local_materialized_prompt_segment",
    "xprompt_trace_segments",
]
