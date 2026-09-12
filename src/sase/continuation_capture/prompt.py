"""Prepared prompt capture persistence."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationPromptSegmentWire,
)

from ._constants import PREPARED_PROMPT_FILENAME, _MAX_SEGMENTS
from ._storage import (
    PublicationTransaction,
    continuation_root,
    local_ref,
    optional_int,
    read_json_object,
    recover_publication_journal,
    required_text,
    update_agent_meta_fields,
    wire_reference_or_none,
    record_capture_error,
)
from .models import ContinuationSegmentCapture, PreparedPromptCaptureResult
from .segments import complete_prompt_segments, wire_segments_from_prepared

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import LoopState


def record_prepared_prompt_capture(
    artifacts_dir: str | os.PathLike[str],
    *,
    authored_local_request: str,
    materialized_prompt: str,
    segments: Sequence[ContinuationSegmentCapture] = (),
    update_meta: bool = True,
) -> PreparedPromptCaptureResult:
    """Persist the prompt provenance prepared for one local agent invocation."""

    root = continuation_root(artifacts_dir)
    recover_publication_journal(root)
    normalized = complete_prompt_segments(
        authored_local_request=authored_local_request,
        materialized_prompt=materialized_prompt,
        segments=segments,
    )
    txn = PublicationTransaction(root)
    materialized_ref, _, materialized_sha, materialized_bytes = txn.write_text_blob(
        materialized_prompt,
    )
    wire_segments: list[ContinuationPromptSegmentWire] = []
    source_details: list[dict[str, str]] = []
    for index, segment in enumerate(normalized[:_MAX_SEGMENTS]):
        text_ref, _, text_sha, text_bytes = txn.write_text_blob(segment.text)
        source_ref = wire_reference_or_none(segment.source_ref)
        segment_id = f"seg:{index:03d}:{segment.provenance}:{text_sha[:16]}"
        wire_segment: ContinuationPromptSegmentWire = {
            "segment_id": segment_id,
            "provenance": segment.provenance,
            "text_ref": text_ref,
            "text_sha256": text_sha,
            "utf8_bytes": text_bytes,
        }
        if source_ref:
            wire_segment["source_ref"] = source_ref
        wire_segments.append(wire_segment)

        detail: dict[str, str] = {"segment_id": segment_id}
        if source_ref:
            detail["source_ref"] = source_ref
        if segment.source_label:
            detail["source_label"] = segment.source_label
        if detail.keys() != {"segment_id"}:
            source_details.append(detail)

    payload: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "prepared_prompt",
        "authored_local_request": authored_local_request,
        "materialized_prompt_ref": materialized_ref,
        "materialized_prompt_sha256": materialized_sha,
        "materialized_prompt_bytes": materialized_bytes,
        "materialized_local_prompt_segments": wire_segments,
        "debug_archive": True,
        "recorded_at_epoch": time.time(),
    }
    if source_details:
        payload["source_details"] = source_details
    prepared_ref, _ = txn.write_pointer(PREPARED_PROMPT_FILENAME, payload=payload)
    txn.commit()
    prepared_path = root / PREPARED_PROMPT_FILENAME
    result = PreparedPromptCaptureResult(
        prepared_ref=prepared_ref,
        prepared_path=str(prepared_path),
        materialized_prompt_ref=materialized_ref,
        materialized_prompt_sha256=materialized_sha,
        materialized_prompt_bytes=materialized_bytes,
        segment_count=len(wire_segments),
    )
    if update_meta:
        update_agent_meta_fields(
            artifacts_dir,
            {
                "continuation_prepared_prompt_ref": result.prepared_ref,
                "continuation_prepared_prompt_path": result.prepared_path,
                "continuation_materialized_prompt_ref": (
                    result.materialized_prompt_ref
                ),
            },
        )
    return result


def record_prepared_prompt_capture_best_effort(
    artifacts_dir: str | os.PathLike[str] | None,
    *,
    authored_local_request: str,
    materialized_prompt: str,
    segments: Sequence[ContinuationSegmentCapture] = (),
) -> PreparedPromptCaptureResult | None:
    """Best-effort wrapper for prepared prompt capture."""

    if artifacts_dir is None:
        return None
    try:
        return record_prepared_prompt_capture(
            artifacts_dir,
            authored_local_request=authored_local_request,
            materialized_prompt=materialized_prompt,
            segments=segments,
        )
    except Exception as exc:
        record_capture_error(artifacts_dir, "prepared_prompt", exc)
        return None


def read_prepared_prompt_capture_ref(
    artifacts_dir: str | os.PathLike[str] | None,
) -> str | None:
    """Return the prepared prompt ref for an artifacts dir, if present."""

    if artifacts_dir is None:
        return None
    payload = read_json_object(
        continuation_root(artifacts_dir) / PREPARED_PROMPT_FILENAME
    )
    if not payload:
        return None
    ref = payload.get("prepared_ref") or local_ref(PREPARED_PROMPT_FILENAME)
    if isinstance(ref, str):
        return ref
    return None


def ensure_prepared_prompt(
    artifacts_dir: str | os.PathLike[str],
    state: LoopState,
    *,
    authored_local_request: str,
) -> PreparedPromptCaptureResult:
    root = continuation_root(artifacts_dir)
    payload = read_json_object(root / PREPARED_PROMPT_FILENAME)
    if payload:
        materialized_ref = required_text(payload.get("materialized_prompt_ref"), "")
        materialized_sha = required_text(
            payload.get("materialized_prompt_sha256"),
            "0" * 64,
        )
        materialized_bytes = optional_int(payload.get("materialized_prompt_bytes")) or 0
        segments = payload.get("materialized_local_prompt_segments")
        segment_count = len(segments) if isinstance(segments, list) else 0
        return PreparedPromptCaptureResult(
            prepared_ref=local_ref(PREPARED_PROMPT_FILENAME),
            prepared_path=str(root / PREPARED_PROMPT_FILENAME),
            materialized_prompt_ref=materialized_ref,
            materialized_prompt_sha256=materialized_sha,
            materialized_prompt_bytes=materialized_bytes,
            segment_count=segment_count,
        )
    return record_prepared_prompt_capture(
        artifacts_dir,
        authored_local_request=authored_local_request,
        materialized_prompt=state.current_prompt,
        segments=(),
    )


__all__ = [
    "read_prepared_prompt_capture_ref",
    "record_prepared_prompt_capture",
    "record_prepared_prompt_capture_best_effort",
]
